import os
import logging
from twisted.internet import defer, threads

from lbrynet import conf
from lbrynet.core.Session import Session
from lbrynet.core.Wallet import LBRYumWallet
from lbrynet.daemon.Component import Component
from lbrynet.database.storage import SQLiteStorage
from lbrynet.dht import node, hashannouncer

from lbrynet.core.utils import generate_id

log = logging.getLogger(__name__)

# settings must be initialized before this file is imported

DATABASE_COMPONENT = "database"
WALLET_COMPONENT = "wallet"
SESSION_COMPONENT = "session"
DHT_COMPONENT = "dht"


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

    def __init__(self, component_mananger):
        Component.__init__(self, component_mananger)
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
    depends_on = [DATABASE_COMPONENT, WALLET_COMPONENT, DHT_COMPONENT]

    def __init__(self, component_mananger):
        Component.__init__(self, component_mananger)
        self.session = None

    @defer.inlineCallbacks
    def setup(self):
        self.session = Session(
            GCS('data_rate'),
            db_dir=GCS('data_dir'),
            node_id=CS.get_node_id(),
            blob_dir=CS.get_blobfiles_dir(),
            dht_node=self.component_manager.get_component(DHT_COMPONENT).dht_node,
            hash_announcer=self.component_manager.get_component(DHT_COMPONENT).dht_node.hash_announcer,
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
    depends_on = [DATABASE_COMPONENT]

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
        if not self.hash_announcer:
            storage = self.component_manager.get_component(DATABASE_COMPONENT).storage
            self.hash_announcer = hashannouncer.DHTHashAnnouncer(self.dht_node, storage)
        yield self.dht_node.joinNetwork(GCS('known_dht_nodes'))
        log.info("Joined the dht")
        yield self.hash_announcer.start()

    @defer.inlineCallbacks
    def stop(self):
        yield self.hash_announcer.stop()
        yield self.dht_node.stop()
