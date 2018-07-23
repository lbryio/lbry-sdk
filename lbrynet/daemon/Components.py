import os
import logging
import miniupnpc
from twisted.internet import defer, threads, reactor, error

from lbrynet import conf
from lbrynet.core.Session import Session
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier, EncryptedFileStreamType
from lbrynet.core.Wallet import LBRYumWallet
from lbrynet.core.server.BlobRequestHandler import BlobRequestHandlerFactory
from lbrynet.core.server.ServerProtocol import ServerProtocolFactory
from lbrynet.daemon.Component import Component
from lbrynet.daemon.ExchangeRateManager import ExchangeRateManager
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
HASH_ANNOUNCER_COMPONENT = "hash_announcer"
STREAM_IDENTIFIER_COMPONENT = "stream_identifier"
FILE_MANAGER_COMPONENT = "file_manager"
PEER_PROTOCOL_SERVER_COMPONENT = "peer_protocol_server"
REFLECTOR_COMPONENT = "reflector"
UPNP_COMPONENT = "upnp"
EXCHANGE_RATE_MANAGER_COMPONENT = "exchange_rate_manager"


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

    @property
    def component(self):
        return self.storage

    @staticmethod
    def get_current_db_revision():
        return 9

    @staticmethod
    def get_revision_filename():
        return conf.settings.get_db_revision_filename()

    @staticmethod
    def _write_db_revision_file(version_num):
        with open(conf.settings.get_db_revision_filename(), mode='w') as db_revision:
            db_revision.write(str(version_num))

    @defer.inlineCallbacks
    def start(self):
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
                dbmigrator.migrate_db, GCS('data_dir'), old_revision, self.get_current_db_revision()
            )
            self._write_db_revision_file(self.get_current_db_revision())
            log.info("Finished upgrading the databases.")

        # start SQLiteStorage
        self.storage = SQLiteStorage(GCS('data_dir'))
        yield self.storage.setup()

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

    @property
    def component(self):
        return self.wallet

    @defer.inlineCallbacks
    def start(self):
        storage = self.component_manager.get_component(DATABASE_COMPONENT)
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

    @property
    def component(self):
        return self.session

    @defer.inlineCallbacks
    def start(self):
        self.session = Session(
            GCS('data_rate'),
            db_dir=GCS('data_dir'),
            node_id=CS.get_node_id(),
            blob_dir=CS.get_blobfiles_dir(),
            dht_node=self.component_manager.get_component(DHT_COMPONENT),
            hash_announcer=self.component_manager.get_component(HASH_ANNOUNCER_COMPONENT),
            dht_node_port=GCS('dht_node_port'),
            known_dht_nodes=GCS('known_dht_nodes'),
            peer_port=GCS('peer_port'),
            wallet=self.component_manager.get_component(WALLET_COMPONENT),
            external_ip=CS.get_external_ip(),
            storage=self.component_manager.get_component(DATABASE_COMPONENT)
        )
        yield self.session.setup()

    @defer.inlineCallbacks
    def stop(self):
        yield self.session.shut_down()


class DHTComponent(Component):
    component_name = DHT_COMPONENT
    depends_on = [UPNP_COMPONENT]

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.dht_node = None
        self.upnp_component = None
        self.udp_port, self.peer_port = None, None

    @property
    def component(self):
        return self.dht_node

    @defer.inlineCallbacks
    def start(self):
        self.upnp_component = self.component_manager.get_component(UPNP_COMPONENT)
        self.peer_port, self.udp_port = self.upnp_component.get_redirects()
        node_id = CS.get_node_id()
        if node_id is None:
            node_id = generate_id()

        self.dht_node = node.Node(
            node_id=node_id,
            udpPort=self.udp_port,
            externalIP=CS.get_external_ip(),
            peerPort=self.peer_port
        )

        self.dht_node.start_listening()
        yield self.dht_node._protocol._listening
        d = self.dht_node.joinNetwork(GCS('known_dht_nodes'))
        d.addCallback(lambda _: self.dht_node.start_looping_calls())
        d.addCallback(lambda _: log.info("Joined the dht"))
        log.info("Started the dht")

    @defer.inlineCallbacks
    def stop(self):
        yield self.dht_node.stop()


class HashAnnouncerComponent(Component):
    component_name = HASH_ANNOUNCER_COMPONENT
    depends_on = [DHT_COMPONENT, DATABASE_COMPONENT]

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.hash_announcer = None

    @property
    def component(self):
        return self.hash_announcer

    @defer.inlineCallbacks
    def start(self):
        storage = self.component_manager.get_component(DATABASE_COMPONENT)
        dht_node = self.component_manager.get_component(DHT_COMPONENT)
        self.hash_announcer = hashannouncer.DHTHashAnnouncer(dht_node, storage)
        yield self.hash_announcer.start()

    @defer.inlineCallbacks
    def stop(self):
        yield self.hash_announcer.stop()


class StreamIdentifierComponent(Component):
    component_name = STREAM_IDENTIFIER_COMPONENT
    depends_on = [SESSION_COMPONENT]

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.sd_identifier = StreamDescriptorIdentifier()

    @property
    def component(self):
        return self.sd_identifier

    @defer.inlineCallbacks
    def start(self):
        session = self.component_manager.get_component(SESSION_COMPONENT)
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


class FileManagerComponent(Component):
    component_name = FILE_MANAGER_COMPONENT
    depends_on = [SESSION_COMPONENT, STREAM_IDENTIFIER_COMPONENT]

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.file_manager = None

    @property
    def component(self):
        return self.file_manager

    @defer.inlineCallbacks
    def start(self):
        session = self.component_manager.get_component(SESSION_COMPONENT)
        sd_identifier = self.component_manager.get_component(STREAM_IDENTIFIER_COMPONENT)
        log.info('Starting the file manager')
        self.file_manager = EncryptedFileManager(session, sd_identifier)
        yield self.file_manager.setup()
        log.info('Done setting up file manager')

    @defer.inlineCallbacks
    def stop(self):
        yield self.file_manager.stop()


class PeerProtocolServerComponent(Component):
    component_name = PEER_PROTOCOL_SERVER_COMPONENT
    depends_on = [SESSION_COMPONENT, UPNP_COMPONENT]

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.lbry_server_port = None

    @property
    def component(self):
        return self.lbry_server_port

    @defer.inlineCallbacks
    def start(self):
        query_handlers = {}
        upnp_component = self.component_manager.get_component(UPNP_COMPONENT)
        peer_port, udp_port = upnp_component.get_redirects()
        session = self.component_manager.get_component(SESSION_COMPONENT)

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


class ReflectorComponent(Component):
    component_name = REFLECTOR_COMPONENT
    depends_on = [SESSION_COMPONENT, FILE_MANAGER_COMPONENT]

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.reflector_server_port = GCS('reflector_port')
        self.reflector_server = None

    @property
    def component(self):
        return self.reflector_server

    @defer.inlineCallbacks
    def start(self):
        log.info("Starting reflector server")

        session = self.component_manager.get_component(SESSION_COMPONENT)
        file_manager = self.component_manager.get_component(FILE_MANAGER_COMPONENT)
        reflector_factory = reflector_server_factory(session.peer_manager, session.blob_manager, file_manager)

        try:
            self.reflector_server = yield reactor.listenTCP(self.reflector_server_port, reflector_factory)
            log.info('Started reflector on port %s', self.reflector_server_port)
        except error.CannotListenError as e:
            log.exception("Couldn't bind reflector to port %d", self.reflector_server_port)
            raise ValueError("{} lbrynet may already be running on your computer.".format(e))

    @defer.inlineCallbacks
    def stop(self):
        if self.reflector_server is not None:
            log.info("Stopping reflector server")
            self.reflector_server, p = None, self.reflector_server
            yield p.stopListening


class UPnPComponent(Component):
    component_name = UPNP_COMPONENT

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.peer_port = GCS('peer_port')
        self.dht_node_port = GCS('dht_node_port')
        self.use_upnp = GCS('use_upnp')
        self.external_ip = CS.get_external_ip()
        self.upnp_redirects = []

    @property
    def component(self):
        return self

    def get_redirects(self):
        return self.peer_port, self.dht_node_port

    def start(self):
        log.debug("In _try_upnp")

        def get_free_port(upnp, port, protocol):
            # returns an existing mapping if it exists
            mapping = upnp.getspecificportmapping(port, protocol)
            if not mapping:
                return port
            if upnp.lanaddr == mapping[0]:
                return mapping[1]
            return get_free_port(upnp, port + 1, protocol)

        def get_port_mapping(upnp, port, protocol, description):
            # try to map to the requested port, if there is already a mapping use the next external
            # port available
            if protocol not in ['UDP', 'TCP']:
                raise Exception("invalid protocol")
            port = get_free_port(upnp, port, protocol)
            if isinstance(port, tuple):
                log.info("Found existing UPnP redirect %s:%i (%s) to %s:%i, using it",
                         self.external_ip, port, protocol, upnp.lanaddr, port)
                return port
            upnp.addportmapping(port, protocol, upnp.lanaddr, port,
                                description, '')
            log.info("Set UPnP redirect %s:%i (%s) to %s:%i", self.external_ip, port,
                     protocol, upnp.lanaddr, port)
            return port

        def threaded_try_upnp():
            if self.use_upnp is False:
                log.debug("Not using upnp")
                return False
            u = miniupnpc.UPnP()
            num_devices_found = u.discover()
            if num_devices_found > 0:
                u.selectigd()
                external_ip = u.externalipaddress()
                if external_ip != '0.0.0.0' and not self.external_ip:
                    # best not to rely on this external ip, the router can be behind layers of NATs
                    self.external_ip = external_ip
                if self.peer_port:
                    self.peer_port = get_port_mapping(u, self.peer_port, 'TCP', 'LBRY peer port')
                    self.upnp_redirects.append((self.peer_port, 'TCP'))
                if self.dht_node_port:
                    self.dht_node_port = get_port_mapping(u, self.dht_node_port, 'UDP', 'LBRY DHT port')
                    self.upnp_redirects.append((self.dht_node_port, 'UDP'))
                return True
            return False

        def upnp_failed(err):
            log.warning("UPnP failed. Reason: %s", err.getErrorMessage())
            return False

        d = threads.deferToThread(threaded_try_upnp)
        d.addErrback(upnp_failed)
        return d

    def stop(self):
        log.info("Unsetting upnp for session")

        def threaded_unset_upnp():
            if self.use_upnp is False:
                log.debug("Not using upnp")
                return False
            u = miniupnpc.UPnP()
            num_devices_found = u.discover()
            if num_devices_found > 0:
                u.selectigd()
                for port, protocol in self.upnp_redirects:
                    if u.getspecificportmapping(port, protocol) is None:
                        log.warning(
                            "UPnP redirect for %s %d was removed by something else.",
                            protocol, port)
                    else:
                        u.deleteportmapping(port, protocol)
                        log.info("Removed UPnP redirect for %s %d.", protocol, port)
                self.upnp_redirects = []

        d = threads.deferToThread(threaded_unset_upnp)
        d.addErrback(lambda err: str(err))
        return d


class ExchangeRateManagerComponent(Component):
    component_name = EXCHANGE_RATE_MANAGER_COMPONENT

    def __init__(self, component_manager):
        Component.__init__(self, component_manager)
        self.exchange_rate_manager = ExchangeRateManager()

    @property
    def component(self):
        return self.exchange_rate_manager

    @defer.inlineCallbacks
    def start(self):
        yield self.exchange_rate_manager.start()

    @defer.inlineCallbacks
    def stop(self):
        yield self.exchange_rate_manager.stop()
