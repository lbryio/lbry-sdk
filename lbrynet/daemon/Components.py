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


class ConfigSettings:
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
    storage = None

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

    @classmethod
    @defer.inlineCallbacks
    def setup(cls):
        # check directories exist, create them if they don't
        log.info("Loading databases")

        if not os.path.exists(GCS('download_directory')):
            os.mkdir(GCS('download_directory'))

        if not os.path.exists(GCS('data_dir')):
            os.mkdir(GCS('data_dir'))
            cls._write_db_revision_file(cls.get_current_db_revision())
            log.debug("Created the db revision file: %s", cls.get_revision_filename())

        if not os.path.exists(CS.get_blobfiles_dir()):
            os.mkdir(CS.get_blobfiles_dir())
            log.debug("Created the blobfile directory: %s", str(CS.get_blobfiles_dir()))

        if not os.path.exists(cls.get_revision_filename()):
            log.warning("db_revision file not found. Creating it")
            cls._write_db_revision_file(cls.get_current_db_revision())

        # check the db migration and run any needed migrations
        migrated = False
        with open(cls.get_revision_filename(), "r") as revision_read_handle:
            old_revision = int(revision_read_handle.read().strip())

        if old_revision > cls.get_current_db_revision():
            raise Exception('This version of lbrynet is not compatible with the database\n'
                            'Your database is revision %i, expected %i' %
                            (old_revision, cls.get_current_db_revision()))
        if old_revision < cls.get_current_db_revision():
            from lbrynet.database.migrator import dbmigrator
            log.info("Upgrading your databases (revision %i to %i)", old_revision, cls.get_current_db_revision())
            yield threads.deferToThread(
                dbmigrator.migrate_db, CS.get_blobfiles_dir(), old_revision, cls.get_current_db_revision()
            )
            cls._write_db_revision_file(cls.get_current_db_revision())
            log.info("Finished upgrading the databases.")
            migrated = True

        # start SQLiteStorage
        cls.storage = SQLiteStorage(CS.get_blobfiles_dir())
        yield cls.storage.setup()
        defer.returnValue(migrated)

    @classmethod
    @defer.inlineCallbacks
    def stop(cls):
        yield cls.storage.stop()


class WalletComponent(Component):
    component_name = WALLET_COMPONENT
    depends_on = [DATABASE_COMPONENT]
    wallet = None
    wallet_type = None

    @classmethod
    @defer.inlineCallbacks
    def setup(cls):
        storage = DatabaseComponent.storage
        cls.wallet_type = GCS('wallet')

        if cls.wallet_type == conf.LBRYCRD_WALLET:
            raise ValueError('LBRYcrd Wallet is no longer supported')
        elif cls.wallet_type == conf.LBRYUM_WALLET:

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
            cls.wallet = LBRYumWallet(storage, config)
            yield cls.wallet.start()
        else:
            raise ValueError('Wallet Type {} is not valid'.format(cls.wallet_type))

    @classmethod
    @defer.inlineCallbacks
    def stop(cls):
        yield cls.wallet.stop()


class SessionComponent(Component):
    component_name = SESSION_COMPONENT
    depends_on = [DATABASE_COMPONENT, WALLET_COMPONENT, DHT_COMPONENT]
    session = None


    @classmethod
    @defer.inlineCallbacks
    def setup(cls):
        wallet = WalletComponent.wallet
        storage = DatabaseComponent.storage
        dht_node = DHTComponennt.dht_node

        log.info("in session setup")

        cls.session = Session(
            GCS('data_rate'),
            db_dir=GCS('data_dir'),
            node_id=CS.get_node_id(),
            blob_dir=CS.get_blobfiles_dir(),
            dht_node=dht_node,
            dht_node_port=GCS('dht_node_port'),
            known_dht_nodes=GCS('known_dht_nodes'),
            peer_port=GCS('peer_port'),
            use_upnp=GCS('use_upnp'),
            wallet=wallet,
            is_generous=GCS('is_generous_host'),
            external_ip=CS.get_external_ip(),
            storage=storage
        )

        yield cls.session.setup()

    @classmethod
    @defer.inlineCallbacks
    def stop(cls):
        yield cls.session.shut_down()


class DHTComponennt(Component):
    component_name = DHT_COMPONENT
    depends_on = [DATABASE_COMPONENT]
    dht_node = None
    dht_node_class = node.Node

    @classmethod
    @defer.inlineCallbacks
    def setup(cls):
        storage = DatabaseComponent.storage

        node_id = CS.get_node_id()
        if node_id is None:
            node_id = generate_id()

        cls.dht_node = cls.dht_node_class(
            node_id=node_id,
            udpPort=GCS('dht_node_port'),
            externalIP=CS.get_external_ip(),
            peerPort=GCS('peer_port')
        )
        if not cls.hash_announcer:
            cls.hash_announcer = hashannouncer.DHTHashAnnouncer(cls.dht_node, storage)
        cls.peer_manager = cls.dht_node.peer_manager
        cls.peer_finder = cls.dht_node.peer_finder
        cls._join_dht_deferred = cls.dht_node.joinNetwork(GCS('known_dht_nodes')())
        cls._join_dht_deferred.addCallback(lambda _: log.info("Joined the dht"))
        cls._join_dht_deferred.addCallback(lambda _: cls.hash_announcer.start())

    @classmethod
    @defer.inlineCallbacks
    def stop(cls):
        raise NotImplementedError()
