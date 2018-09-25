import os
import logging
import treq
import math
import binascii
from hashlib import sha256
from types import SimpleNamespace
from twisted.internet import defer, threads, reactor, error
import lbryschema
from txupnp.upnp import UPnP
from lbrynet import conf
from lbrynet.core.utils import DeferredDict
from lbrynet.core.PaymentRateManager import OnlyFreePaymentsManager
from lbrynet.core.RateLimiter import RateLimiter
from lbrynet.core.BlobManager import DiskBlobManager
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier, EncryptedFileStreamType
from lbrynet.wallet.manager import LbryWalletManager
from lbrynet.wallet.network import Network
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
BLOB_COMPONENT = "blob_manager"
HEADERS_COMPONENT = "blockchain_headers"
WALLET_COMPONENT = "wallet"
DHT_COMPONENT = "dht"
HASH_ANNOUNCER_COMPONENT = "hash_announcer"
STREAM_IDENTIFIER_COMPONENT = "stream_identifier"
FILE_MANAGER_COMPONENT = "file_manager"
PEER_PROTOCOL_SERVER_COMPONENT = "peer_protocol_server"
REFLECTOR_COMPONENT = "reflector"
UPNP_COMPONENT = "upnp"
EXCHANGE_RATE_MANAGER_COMPONENT = "exchange_rate_manager"
RATE_LIMITER_COMPONENT = "rate_limiter"
PAYMENT_RATE_COMPONENT = "payment_rate_manager"


def get_wallet_config():
    wallet_type = GCS('wallet')
    if wallet_type == conf.LBRYCRD_WALLET:
        raise ValueError('LBRYcrd Wallet is no longer supported')
    elif wallet_type != conf.LBRYUM_WALLET:
        raise ValueError('Wallet Type {} is not valid'.format(wallet_type))
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
    return config


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

    def __init__(self, component_manager):
        super().__init__(component_manager)
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


HEADERS_URL = "https://headers.lbry.io/blockchain_headers_latest"
HEADER_SIZE = 112


class HeadersComponent(Component):
    component_name = HEADERS_COMPONENT

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.headers_dir = os.path.join(conf.settings['lbryum_wallet_dir'], 'lbc_mainnet')
        self.headers_file = os.path.join(self.headers_dir, 'headers')
        self.old_file = os.path.join(conf.settings['lbryum_wallet_dir'], 'blockchain_headers')
        self._downloading_headers = None
        self._headers_progress_percent = None

    @property
    def component(self):
        return self

    def get_status(self):
        return {} if not self._downloading_headers else {
            'downloading_headers': self._downloading_headers,
            'download_progress': self._headers_progress_percent
        }

    @defer.inlineCallbacks
    def fetch_headers_from_s3(self):
        def collector(data, h_file):
            h_file.write(data)
            local_size = float(h_file.tell())
            final_size = float(final_size_after_download)
            self._headers_progress_percent = math.ceil(local_size / final_size * 100)

        local_header_size = self.local_header_file_size()
        resume_header = {"Range": "bytes={}-".format(local_header_size)}
        response = yield treq.get(HEADERS_URL, headers=resume_header)
        got_406 = response.code == 406  # our file is bigger
        final_size_after_download = response.length + local_header_size
        if got_406:
            log.warning("s3 is more out of date than we are")
        # should have something to download and a final length divisible by the header size
        elif final_size_after_download and not final_size_after_download % HEADER_SIZE:
            s3_height = (final_size_after_download / HEADER_SIZE) - 1
            local_height = self.local_header_file_height()
            if s3_height > local_height:
                if local_header_size:
                    log.info("Resuming download of %i bytes from s3", response.length)
                    with open(self.headers_file, "a+b") as headers_file:
                        yield treq.collect(response, lambda d: collector(d, headers_file))
                else:
                    with open(self.headers_file, "wb") as headers_file:
                        yield treq.collect(response, lambda d: collector(d, headers_file))
                log.info("fetched headers from s3 (s3 height: %i), now verifying integrity after download.", s3_height)
                self._check_header_file_integrity()
            else:
                log.warning("s3 is more out of date than we are")
        else:
            log.error("invalid size for headers from s3")

    def local_header_file_height(self):
        return max((self.local_header_file_size() / HEADER_SIZE) - 1, 0)

    def local_header_file_size(self):
        if os.path.isfile(self.headers_file):
            return os.stat(self.headers_file).st_size
        return 0

    @defer.inlineCallbacks
    def get_remote_height(self):
        ledger = SimpleNamespace()
        ledger.config = {
            'default_servers': conf.settings['lbryum_servers'],
            'data_path': conf.settings['lbryum_wallet_dir']
        }
        net = Network(ledger)
        net.start()
        yield net.on_connected.first
        remote_height = yield net.get_server_height()
        yield net.stop()
        defer.returnValue(remote_height)

    @defer.inlineCallbacks
    def should_download_headers_from_s3(self):
        if conf.settings['blockchain_name'] != "lbrycrd_main":
            defer.returnValue(False)
        self._check_header_file_integrity()
        s3_headers_depth = conf.settings['s3_headers_depth']
        if not s3_headers_depth:
            defer.returnValue(False)
        local_height = self.local_header_file_height()
        remote_height = yield self.get_remote_height()
        log.info("remote height: %i, local height: %s", remote_height, local_height)
        if remote_height > (local_height + s3_headers_depth):
            defer.returnValue(True)
        defer.returnValue(False)

    def _check_header_file_integrity(self):
        # TODO: temporary workaround for usability. move to txlbryum and check headers instead of file integrity
        if conf.settings['blockchain_name'] != "lbrycrd_main":
            return
        hashsum = sha256()
        checksum_height, checksum = conf.settings['HEADERS_FILE_SHA256_CHECKSUM']
        checksum_length_in_bytes = checksum_height * HEADER_SIZE
        if self.local_header_file_size() < checksum_length_in_bytes:
            return
        with open(self.headers_file, "rb") as headers_file:
            hashsum.update(headers_file.read(checksum_length_in_bytes))
        current_checksum = hashsum.hexdigest()
        if current_checksum != checksum:
            msg = "Expected checksum {}, got {}".format(checksum, current_checksum)
            log.warning("Wallet file corrupted, checksum mismatch. " + msg)
            log.warning("Deleting header file so it can be downloaded again.")
            os.unlink(self.headers_file)
        elif (self.local_header_file_size() % HEADER_SIZE) != 0:
            log.warning("Header file is good up to checkpoint height, but incomplete. Truncating to checkpoint.")
            with open(self.headers_file, "rb+") as headers_file:
                headers_file.truncate(checksum_length_in_bytes)

    @defer.inlineCallbacks
    def start(self):
        if not os.path.exists(self.headers_dir):
            os.mkdir(self.headers_dir)
        if os.path.exists(self.old_file):
            log.warning("Moving old headers from %s to %s.", self.old_file, self.headers_file)
            os.rename(self.old_file, self.headers_file)
        self._downloading_headers = yield self.should_download_headers_from_s3()
        if self._downloading_headers:
            try:
                yield self.fetch_headers_from_s3()
            except Exception as err:
                log.error("failed to fetch headers from s3: %s", err)
            finally:
                self._downloading_headers = False

    def stop(self):
        return defer.succeed(None)


class WalletComponent(Component):
    component_name = WALLET_COMPONENT
    depends_on = [DATABASE_COMPONENT, HEADERS_COMPONENT]

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.wallet_manager = None

    @property
    def component(self):
        return self.wallet_manager

    @defer.inlineCallbacks
    def get_status(self):
        if self.wallet_manager:
            local_height = self.wallet_manager.network.get_local_height()
            remote_height = self.wallet_manager.network.get_server_height()
            best_hash = yield self.wallet_manager.get_best_blockhash()
            defer.returnValue({
                'blocks': max(local_height, 0),
                'blocks_behind': max(remote_height - local_height, 0),
                'best_blockhash': best_hash,
                'is_encrypted': self.wallet_manager.wallet.use_encryption,
                'is_locked': not self.wallet_manager.is_wallet_unlocked,
            })

    @defer.inlineCallbacks
    def start(self):
        log.info("Starting torba wallet")
        storage = self.component_manager.get_component(DATABASE_COMPONENT)
        lbryschema.BLOCKCHAIN_NAME = conf.settings['blockchain_name']
        self.wallet_manager = LbryWalletManager.from_lbrynet_config(conf.settings, storage)
        self.wallet_manager.old_db = storage
        yield self.wallet_manager.start()

    @defer.inlineCallbacks
    def stop(self):
        yield self.wallet_manager.stop()
        self.wallet_manager = None


class BlobComponent(Component):
    component_name = BLOB_COMPONENT
    depends_on = [DATABASE_COMPONENT, DHT_COMPONENT]

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.blob_manager = None

    @property
    def component(self):
        return self.blob_manager

    def start(self):
        storage = self.component_manager.get_component(DATABASE_COMPONENT)
        dht_node = self.component_manager.get_component(DHT_COMPONENT)
        self.blob_manager = DiskBlobManager(CS.get_blobfiles_dir(), storage, dht_node._dataStore)
        return self.blob_manager.setup()

    def stop(self):
        return self.blob_manager.stop()

    @defer.inlineCallbacks
    def get_status(self):
        count = 0
        if self.blob_manager:
            count = yield self.blob_manager.storage.count_finished_blobs()
        defer.returnValue({
            'finished_blobs': count
        })


class DHTComponent(Component):
    component_name = DHT_COMPONENT
    depends_on = [UPNP_COMPONENT]

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.dht_node = None
        self.upnp_component = None
        self.external_udp_port = None
        self.external_peer_port = None

    @property
    def component(self):
        return self.dht_node

    def get_status(self):
        return {
            'node_id': binascii.hexlify(CS.get_node_id()),
            'peers_in_routing_table': 0 if not self.dht_node else len(self.dht_node.contacts)
        }

    @defer.inlineCallbacks
    def start(self):
        self.upnp_component = self.component_manager.get_component(UPNP_COMPONENT)
        self.external_peer_port = self.upnp_component.upnp_redirects.get("TCP", GCS("peer_port"))
        self.external_udp_port = self.upnp_component.upnp_redirects.get("UDP", GCS("dht_node_port"))
        node_id = CS.get_node_id()
        if node_id is None:
            node_id = generate_id()

        self.dht_node = node.Node(
            node_id=node_id,
            udpPort=GCS('dht_node_port'),
            externalUDPPort=self.external_udp_port,
            externalIP=self.upnp_component.external_ip,
            peerPort=self.external_peer_port
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
        super().__init__(component_manager)
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

    def get_status(self):
        return {
            'announce_queue_size': 0 if not self.hash_announcer else len(self.hash_announcer.hash_queue)
        }


class RateLimiterComponent(Component):
    component_name = RATE_LIMITER_COMPONENT

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.rate_limiter = RateLimiter()

    @property
    def component(self):
        return self.rate_limiter

    def start(self):
        self.rate_limiter.start()
        return defer.succeed(None)

    def stop(self):
        self.rate_limiter.stop()
        return defer.succeed(None)


class StreamIdentifierComponent(Component):
    component_name = STREAM_IDENTIFIER_COMPONENT
    depends_on = [DHT_COMPONENT, RATE_LIMITER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT, WALLET_COMPONENT]

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.sd_identifier = StreamDescriptorIdentifier()

    @property
    def component(self):
        return self.sd_identifier

    @defer.inlineCallbacks
    def start(self):
        dht_node = self.component_manager.get_component(DHT_COMPONENT)
        rate_limiter = self.component_manager.get_component(RATE_LIMITER_COMPONENT)
        blob_manager = self.component_manager.get_component(BLOB_COMPONENT)
        storage = self.component_manager.get_component(DATABASE_COMPONENT)
        wallet = self.component_manager.get_component(WALLET_COMPONENT)

        add_lbry_file_to_sd_identifier(self.sd_identifier)
        file_saver_factory = EncryptedFileSaverFactory(
            dht_node.peer_finder,
            rate_limiter,
            blob_manager,
            storage,
            wallet,
            GCS('download_directory')
        )
        yield self.sd_identifier.add_stream_downloader_factory(EncryptedFileStreamType, file_saver_factory)

    def stop(self):
        pass


class PaymentRateComponent(Component):
    component_name = PAYMENT_RATE_COMPONENT

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.payment_rate_manager = OnlyFreePaymentsManager()

    @property
    def component(self):
        return self.payment_rate_manager

    def start(self):
        return defer.succeed(None)

    def stop(self):
        return defer.succeed(None)


class FileManagerComponent(Component):
    component_name = FILE_MANAGER_COMPONENT
    depends_on = [DHT_COMPONENT, RATE_LIMITER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT, WALLET_COMPONENT,
                  STREAM_IDENTIFIER_COMPONENT, PAYMENT_RATE_COMPONENT]

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.file_manager = None

    @property
    def component(self):
        return self.file_manager

    def get_status(self):
        if not self.file_manager:
            return
        return {
            'managed_files': len(self.file_manager.lbry_files)
        }

    @defer.inlineCallbacks
    def start(self):
        dht_node = self.component_manager.get_component(DHT_COMPONENT)
        rate_limiter = self.component_manager.get_component(RATE_LIMITER_COMPONENT)
        blob_manager = self.component_manager.get_component(BLOB_COMPONENT)
        storage = self.component_manager.get_component(DATABASE_COMPONENT)
        wallet = self.component_manager.get_component(WALLET_COMPONENT)
        sd_identifier = self.component_manager.get_component(STREAM_IDENTIFIER_COMPONENT)
        payment_rate_manager = self.component_manager.get_component(PAYMENT_RATE_COMPONENT)
        log.info('Starting the file manager')
        self.file_manager = EncryptedFileManager(dht_node.peer_finder, rate_limiter, blob_manager, wallet,
                                                 payment_rate_manager, storage, sd_identifier)
        yield self.file_manager.setup()
        log.info('Done setting up file manager')

    @defer.inlineCallbacks
    def stop(self):
        yield self.file_manager.stop()


class PeerProtocolServerComponent(Component):
    component_name = PEER_PROTOCOL_SERVER_COMPONENT
    depends_on = [UPNP_COMPONENT, DHT_COMPONENT, RATE_LIMITER_COMPONENT, BLOB_COMPONENT, WALLET_COMPONENT,
                  PAYMENT_RATE_COMPONENT]

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.lbry_server_port = None

    @property
    def component(self):
        return self.lbry_server_port

    @defer.inlineCallbacks
    def start(self):
        wallet = self.component_manager.get_component(WALLET_COMPONENT)
        upnp = self.component_manager.get_component(UPNP_COMPONENT)
        peer_port = GCS('peer_port')
        query_handlers = {
            handler.get_primary_query_identifier(): handler for handler in [
                BlobRequestHandlerFactory(
                    self.component_manager.get_component(BLOB_COMPONENT),
                    wallet,
                    self.component_manager.get_component(PAYMENT_RATE_COMPONENT),
                    self.component_manager.analytics_manager
                ),
                wallet.get_wallet_info_query_handler_factory(),
            ]
        }
        server_factory = ServerProtocolFactory(
            self.component_manager.get_component(RATE_LIMITER_COMPONENT), query_handlers,
            self.component_manager.get_component(DHT_COMPONENT).peer_manager
        )

        try:
            log.info("Peer protocol listening on TCP %i (ext port %i)", peer_port,
                     upnp.upnp_redirects.get("TCP", peer_port))
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
    depends_on = [DHT_COMPONENT, BLOB_COMPONENT, FILE_MANAGER_COMPONENT]

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.reflector_server_port = GCS('reflector_port')
        self.reflector_server = None

    @property
    def component(self):
        return self.reflector_server

    @defer.inlineCallbacks
    def start(self):
        log.info("Starting reflector server")
        dht_node = self.component_manager.get_component(DHT_COMPONENT)
        blob_manager = self.component_manager.get_component(BLOB_COMPONENT)
        file_manager = self.component_manager.get_component(FILE_MANAGER_COMPONENT)
        reflector_factory = reflector_server_factory(dht_node.peer_manager, blob_manager, file_manager)
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
        super().__init__(component_manager)
        self._int_peer_port = GCS('peer_port')
        self._int_dht_node_port = GCS('dht_node_port')
        self.use_upnp = GCS('use_upnp')
        self.upnp = None
        self.upnp_redirects = {}
        self.external_ip = None

    @property
    def component(self):
        return self

    @defer.inlineCallbacks
    def _setup_redirects(self):
        upnp_redirects = yield DeferredDict({
            "UDP": self.upnp.get_next_mapping(self._int_dht_node_port, "UDP", "LBRY DHT port"),
            "TCP": self.upnp.get_next_mapping(self._int_peer_port, "TCP", "LBRY peer port")
        })
        self.upnp_redirects.update(upnp_redirects)

    @defer.inlineCallbacks
    def start(self):
        if not self.use_upnp:
            self.external_ip = CS.get_external_ip()
            return
        self.upnp = UPnP(self.component_manager.reactor, try_miniupnpc_fallback=True)
        try:
            found = yield self.upnp.discover()
        except Exception as err:
            log.warning("upnp discovery failed: %s", err)
            found = False
        if found and not self.upnp.miniupnpc_runner:
            log.info("set up redirects using txupnp")
        elif found and self.upnp.miniupnpc_runner:
            log.warning("failed to set up redirect with txupnp, miniupnpc fallback was successful")
        if found:
            try:
                self.external_ip = yield self.upnp.get_external_ip()
                yield self._setup_redirects()
            except Exception as err:
                log.warning("error trying to set up upnp: %s", err)
                self.external_ip = CS.get_external_ip()
        else:
            self.external_ip = CS.get_external_ip()

    def stop(self):
        return defer.DeferredList(
            [self.upnp.delete_port_mapping(port, protocol) for protocol, port in self.upnp_redirects.items()]
        )


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
