import os
import logging
from twisted.internet import defer, threads
from lbrynet import conf
from lbrynet.database.storage import SQLiteStorage
from lbrynet.core.Wallet import LBRYumWallet
from lbrynet.daemon.Component import Component
# from lbrynet.daemon import ComponentManager

log = logging.getLogger(__name__)

# settings must be initialized before this file is imported

DATABASE_COMPONENT = "database"
WALLET_COMPONENT = "wallet"


class DatabaseComponent(Component):
    component_name = DATABASE_COMPONENT
    storage = None

    @staticmethod
    def get_db_dir():
        return conf.settings['data_dir']

    @staticmethod
    def get_download_directory():
        return conf.settings['download_directory']

    @staticmethod
    def get_blobfile_dir():
        return conf.settings['BLOBFILES_DIR']

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
        if not os.path.exists(cls.get_download_directory()):
            os.mkdir(cls.get_download_directory())
        if not os.path.exists(cls.get_db_dir()):
            os.mkdir(cls.get_db_dir())
            cls._write_db_revision_file(cls.get_current_db_revision())
            log.debug("Created the db revision file: %s", cls.get_revision_filename())
        if not os.path.exists(cls.get_blobfile_dir()):
            os.mkdir(cls.get_blobfile_dir())
            log.debug("Created the blobfile directory: %s", str(cls.get_blobfile_dir()))
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
                dbmigrator.migrate_db, cls.get_db_dir(), old_revision, cls.get_current_db_revision()
            )
            cls._write_db_revision_file(cls.get_current_db_revision())
            log.info("Finished upgrading the databases.")
            migrated = True

        # start SQLiteStorage
        cls.storage = SQLiteStorage(cls.get_db_dir())
        yield cls.storage.setup()
        defer.returnValue(migrated)

    @classmethod
    @defer.inlineCallbacks
    def stop(cls):
        yield cls.storage.stop()


class WalletComponent(Component):
    component_name = WALLET_COMPONENT
    depends_on = ['database']
    wallet = None

    @staticmethod
    def get_wallet_type():
        return conf.settings['wallet']

    @classmethod
    @defer.inlineCallbacks
    def setup(cls):
        storage = DatabaseComponent.storage
        if cls.get_wallet_type() == conf.LBRYCRD_WALLET:
            raise ValueError('LBRYcrd Wallet is no longer supported')
        elif cls.get_wallet_type() == conf.LBRYUM_WALLET:

            log.info("Using lbryum wallet")

            lbryum_servers = {address: {'t': str(port)}
                              for address, port in conf.settings['lbryum_servers']}

            config = {
                'auto_connect': True,
                'chain': conf.settings['blockchain_name'],
                'default_servers': lbryum_servers
            }

            if 'use_keyring' in conf.settings:
                config['use_keyring'] = conf.settings['use_keyring']
            if conf.settings['lbryum_wallet_dir']:
                config['lbryum_path'] = conf.settings['lbryum_wallet_dir']
            cls.wallet = LBRYumWallet(storage, config)
            yield cls.wallet.start()
        else:
            raise ValueError('Wallet Type {} is not valid'.format(cls.get_wallet_type()))

    @classmethod
    @defer.inlineCallbacks
    def stop(cls):
        yield cls.wallet.stop()
