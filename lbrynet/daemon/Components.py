import os
import logging
from twisted.internet import defer, threads, reactor, error

from lbrynet import conf
from lbrynet.core.Session import Session
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier, EncryptedFileStreamType
from lbrynet.core.Wallet import LBRYumWallet
from lbrynet.core.server.BlobRequestHandler import BlobRequestHandlerFactory
from lbrynet.core.server.ServerProtocol import ServerProtocolFactory
from lbrynet.daemon.Component import Component
from lbrynet.database.storage import SQLiteStorage
from lbrynet.dht import node, hashannouncer
from lbrynet.file_manager.EncryptedFileManager import EncryptedFileManager
from lbrynet.lbry_file.client.EncryptedFileDownloader import EncryptedFileSaverFactory
from lbrynet.lbry_file.client.EncryptedFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.reflector import ServerFactory as reflector_server_factory

from lbrynet.core.utils import generate_id

log = logging.getLogger(__name__)

# settings must be initialized before this file is imported

DATABASE_COMPONENT = "database"
WALLET_COMPONENT = "wallet"
SESSION_COMPONENT = "session"
DHT_COMPONENT = "dht"
HASH_ANNOUNCER_COMPONENT = "hashAnnouncer"
STREAM_IDENTIFIER_COMPONENT = "streamIdentifier"
FILE_MANAGER_COMPONENT = "fileManager"
QUERY_HANDLER_COMPONENT = "queryHandler"
SERVER_COMPONENT = "peerProtocolServer"
REFLECTOR_COMPONENT = "reflector"


class ConfigSettings(object):
    @staticmethod
    def get_conf_setting(setting_name):
        return conf.settings[setting_name]

    @staticmethod
    def get_blobfiles_dir():
        if conf.settings['BLOBFILES_DIR'] == "blobfiles":
            return os.path.join(GCS("data_dir"), "blobfiles")
        else:
            log.info("Using non-default blobfiles directory: %s", conf.settings['BLOBFILES_DIR'])
            return conf.settings['BLOBFILES_DIR']

    @staticmethod
    def get_node_id():
        return conf.settings.node_id

    @staticmethod
    def get_external_ip():
        from lbrynet.core.system_info import get_platform
        platform = get_platform(get_ip=True)
        return platform['ip']


# Shorthand for common ConfigSettings methods
CS = ConfigSettings
GCS = ConfigSettings.get_conf_setting


class DatabaseComponent(Component):
    component_name = DATABASE_COMPONENT

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.storage = None

    @staticmethod
    def get_current_db_revision():
        return 7

    @staticmethod
    def get_revision_filename():
        return conf.settings.get_db_revision_filename()

    @staticmethod
    def _write_db_revision_file(version_num):
        with open(conf.settings.get_db_revision_filename(), mode='w') as db_revision:
            db_revision.write(str(version_num))

    @defer.inlineCallbacks
    def setup(self):
        # check directories exist, create them if they don't
        log.info("Loading databases")

        if not os.path.exists(GCS('download_directory')):
            os.mkdir(GCS('download_directory'))

        if not os.path.exists(GCS('data_dir')):
            os.mkdir(GCS('data_dir'))
            self._write_db_revision_file(self.get_current_db_revision())
            log.debug("Created the db revision file: %s", self.get_revision_filename())

        if not os.path.exists(CS.get_blobfiles_dir()):
            os.mkdir(CS.get_blobfiles_dir())
            log.debug("Created the blobfile directory: %s", str(CS.get_blobfiles_dir()))

        if not os.path.exists(self.get_revision_filename()):
            log.warning("db_revision file not found. Creating it")
            self._write_db_revision_file(self.get_current_db_revision())

        # check the db migration and run any needed migrations
        migrated = False
        with open(self.get_revision_filename(), "r") as revision_read_handle:
            old_revision = int(revision_read_handle.read().strip())

        if old_revision > self.get_current_db_revision():
            raise Exception('This version of lbrynet is not compatible with the database\n'
                            'Your database is revision %i, expected %i' %
                            (old_revision, self.get_current_db_revision()))
        if old_revision < self.get_current_db_revision():
            from lbrynet.database.migrator import dbmigrator
            log.info("Upgrading your databases (revision %i to %i)", old_revision, self.get_current_db_revision())
            yield threads.deferToThread(
                dbmigrator.migrate_db, CS.get_blobfiles_dir(), old_revision, self.get_current_db_revision()
            )
            self._write_db_revision_file(self.get_current_db_revision())
            log.info("Finished upgrading the databases.")
            migrated = True

        # start SQLiteStorage
        self.storage = SQLiteStorage(CS.get_blobfiles_dir())
        yield self.storage.setup()
        defer.returnValue(migrated)

    @defer.inlineCallbacks
    def stop(self):
        yield self.storage.stop()
        self.storage = None


class WalletComponent(Component):
    component_name = WALLET_COMPONENT
    depends_on = [DATABASE_COMPONENT]

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.wallet = None

    @defer.inlineCallbacks
    def setup(self):
        storage = self.component_manager.get_component(DATABASE_COMPONENT).storage
        wallet_type = GCS('wallet')

        if wallet_type == conf.LBRYCRD_WALLET:
            raise ValueError('LBRYcrd Wallet is no longer supported')
        elif wallet_type == conf.LBRYUM_WALLET:

            log.info("Using lbryum wallet")

            lbryum_servers = {address: {'t': str(port)}
                              for address, port in GCS('lbryum_servers')}

            config = {
                'auto_connect': True,
                'chain': GCS('blockchain_name'),
                'default_servers': lbryum_servers
            }

            if 'use_keyring' in conf.settings:
                config['use_keyring'] = GCS('use_keyring')
            if conf.settings['lbryum_wallet_dir']:
                config['lbryum_path'] = GCS('lbryum_wallet_dir')
            self.wallet = LBRYumWallet(storage, config)
            yield self.wallet.start()
        else:
            raise ValueError('Wallet Type {} is not valid'.format(wallet_type))

    @defer.inlineCallbacks
    def stop(self):
        yield self.wallet.stop()
        self.wallet = None


class SessionComponent(Component):
    component_name = SESSION_COMPONENT
    depends_on = [DATABASE_COMPONENT, WALLET_COMPONENT, DHT_COMPONENT, HASH_ANNOUNCER_COMPONENT]

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.session = None

    @defer.inlineCallbacks
    def setup(self):
        self.session = Session(
            GCS('data_rate'),
            db_dir=GCS('data_dir'),
            node_id=CS.get_node_id(),
            blob_dir=CS.get_blobfiles_dir(),
            dht_node=self.component_manager.get_component(DHT_COMPONENT).dht_node,
            hash_announcer=self.component_manager.get_component(HASH_ANNOUNCER_COMPONENT).hash_announcer,
            dht_node_port=GCS('dht_node_port'),
            known_dht_nodes=GCS('known_dht_nodes'),
            peer_port=GCS('peer_port'),
            use_upnp=GCS('use_upnp'),
            wallet=self.component_manager.get_component(WALLET_COMPONENT).wallet,
            is_generous=GCS('is_generous_host'),
            external_ip=CS.get_external_ip(),
            storage=self.component_manager.get_component(DATABASE_COMPONENT).storage
        )
        yield self.session.setup()

    @defer.inlineCallbacks
    def stop(self):
        yield self.session.shut_down()


class DHTComponent(Component):
    component_name = DHT_COMPONENT

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.dht_node = None

    @defer.inlineCallbacks
    def setup(self):
        node_id = CS.get_node_id()
        if node_id is None:
            node_id = generate_id()

        self.dht_node = node.Node(
            node_id=node_id,
            udpPort=GCS('dht_node_port'),
            externalIP=CS.get_external_ip(),
            peerPort=GCS('peer_port')
        )
        yield self.dht_node.joinNetwork(GCS('known_dht_nodes'))
        log.info("Joined the dht")

    @defer.inlineCallbacks
    def stop(self):
        yield self.dht_node.stop()


class HashAnnouncer(Component):
    component_name = HASH_ANNOUNCER_COMPONENT
    depends_on = [DHT_COMPONENT, DATABASE_COMPONENT]

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.hash_announcer = None

    @defer.inlineCallbacks
    def setup(self):
        storage = self.component_manager.get_component(DATABASE_COMPONENT).storage
        dht_node = self.component_manager.get_component(DHT_COMPONENT).dht_node
        self.hash_announcer = hashannouncer.DHTHashAnnouncer(dht_node, storage)
        yield self.hash_announcer.start()

    @defer.inlineCallbacks
    def stop(self):
        yield self.hash_announcer.stop()


class StreamIdentifier(Component):
    component_name = STREAM_IDENTIFIER_COMPONENT
    depends_on = [SESSION_COMPONENT]

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.sd_identifier = StreamDescriptorIdentifier()

    @defer.inlineCallbacks
    def setup(self):
        session = self.component_manager.get_component(SESSION_COMPONENT).session
        add_lbry_file_to_sd_identifier(self.sd_identifier)
        file_saver_factory = EncryptedFileSaverFactory(
            session.peer_finder,
            session.rate_limiter,
            session.blob_manager,
            session.storage,
            session.wallet,
            GCS('download_directory')
        )
        yield self.sd_identifier.add_stream_downloader_factory(EncryptedFileStreamType, file_saver_factory)

    def stop(self):
        pass


class FileManager(Component):
    component_name = FILE_MANAGER_COMPONENT
    depends_on = [SESSION_COMPONENT, STREAM_IDENTIFIER_COMPONENT]

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.file_manager = None

    @defer.inlineCallbacks
    def setup(self):
        session = self.component_manager.get_component(SESSION_COMPONENT).session
        sd_identifier = self.component_manager.get_component(STREAM_IDENTIFIER_COMPONENT).sd_identifier
        log.info('Starting the file manager')
        self.file_manager = EncryptedFileManager(session, sd_identifier)
        yield self.file_manager.setup()
        log.info('Done setting up file manager')

    @defer.inlineCallbacks
    def stop(self):
        yield self.file_manager.stop()


class PeerProtocolServer(Component):
    component_name = SERVER_COMPONENT
    depends_on = [SESSION_COMPONENT]

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.lbry_server_port = None

    @defer.inlineCallbacks
    def setup(self):
        query_handlers = {}
        peer_port = GCS('peer_port')
        session = self.component_manager.get_component(SESSION_COMPONENT).session

        handlers = [
            BlobRequestHandlerFactory(
                session.blob_manager,
                session.wallet,
                session.payment_rate_manager,
                self.component_manager.analytics_manager
            ),
            session.wallet.get_wallet_info_query_handler_factory(),
        ]

        for handler in handlers:
            query_id = handler.get_primary_query_identifier()
            query_handlers[query_id] = handler

        if peer_port is not None:
            server_factory = ServerProtocolFactory(session.rate_limiter, query_handlers, session.peer_manager)

            try:
                log.info("Peer protocol listening on TCP %d", peer_port)
                self.lbry_server_port = yield reactor.listenTCP(peer_port, server_factory)
            except error.CannotListenError as e:
                import traceback
                log.error("Couldn't bind to port %d. Visit lbry.io/faq/how-to-change-port for"
                          " more details.", peer_port)
                log.error("%s", traceback.format_exc())
                raise ValueError("%s lbrynet may already be running on your computer." % str(e))

    @defer.inlineCallbacks
    def stop(self):
        if self.lbry_server_port is not None:
            self.lbry_server_port, old_port = None, self.lbry_server_port
            log.info('Stop listening on port %s', old_port.port)
            yield old_port.stopListening()


class Reflector(Component):
    component_name = REFLECTOR_COMPONENT
    depends_on = [SESSION_COMPONENT, FILE_MANAGER_COMPONENT]

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.reflector_server_port = GCS('reflector_port')
        self.run_reflector_server = GCS('run_reflector_server')

    @defer.inlineCallbacks
    def setup(self):
        session = self.component_manager.get_component(SESSION_COMPONENT).session
        file_manager = self.component_manager.get_component(FILE_MANAGER_COMPONENT).file_manager

        if self.run_reflector_server and self.reflector_server_port is not None:
            log.info("Starting reflector server")
            reflector_factory = reflector_server_factory(session.peer_manager, session.blob_manager, file_manager)
            try:
                self.reflector_server_port = yield reactor.listenTCP(self.reflector_server_port, reflector_factory)
                log.info('Started reflector on port %s', self.reflector_server_port)
            except error.CannotListenError as e:
                log.exception("Couldn't bind reflector to port %d", self.reflector_server_port)
                raise ValueError("{} lbrynet may already be running on your computer.".format(e))

    def stop(self):
        if self.run_reflector_server and self.reflector_server_port is not None:
            log.info("Stopping reflector server")
            if self.reflector_server_port is not None:
                self.reflector_server_port, p = None, self.reflector_server_port
                yield p.stopListening
