import hashlib
import os
import asyncio
import logging
import math
import binascii
import typing
import base58

from aioupnp import __version__ as aioupnp_version
from aioupnp.upnp import UPnP
from aioupnp.fault import UPnPError

from lbry import utils
from lbry.dht.node import Node
from lbry.dht.blob_announcer import BlobAnnouncer
from lbry.blob.blob_manager import BlobManager
from lbry.blob_exchange.server import BlobServer
from lbry.stream.stream_manager import StreamManager
from lbry.extras.daemon.Component import Component
from lbry.extras.daemon.exchange_rate_manager import ExchangeRateManager
from lbry.extras.daemon.storage import SQLiteStorage
from lbry.wallet import LbryWalletManager
from lbry.wallet.header import Headers

log = logging.getLogger(__name__)

# settings must be initialized before this file is imported

DATABASE_COMPONENT = "database"
BLOB_COMPONENT = "blob_manager"
HEADERS_COMPONENT = "blockchain_headers"
WALLET_COMPONENT = "wallet"
DHT_COMPONENT = "dht"
HASH_ANNOUNCER_COMPONENT = "hash_announcer"
STREAM_MANAGER_COMPONENT = "stream_manager"
PEER_PROTOCOL_SERVER_COMPONENT = "peer_protocol_server"
UPNP_COMPONENT = "upnp"
EXCHANGE_RATE_MANAGER_COMPONENT = "exchange_rate_manager"


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
        return 11

    @property
    def revision_filename(self):
        return os.path.join(self.conf.data_dir, 'db_revision')

    def _write_db_revision_file(self, version_num):
        with open(self.revision_filename, mode='w') as db_revision:
            db_revision.write(str(version_num))

    async def start(self):
        # check directories exist, create them if they don't
        log.info("Loading databases")

        if not os.path.exists(self.revision_filename):
            log.warning("db_revision file not found. Creating it")
            self._write_db_revision_file(self.get_current_db_revision())

        # check the db migration and run any needed migrations
        with open(self.revision_filename, "r") as revision_read_handle:
            old_revision = int(revision_read_handle.read().strip())

        if old_revision > self.get_current_db_revision():
            raise Exception('This version of lbrynet is not compatible with the database\n'
                            'Your database is revision %i, expected %i' %
                            (old_revision, self.get_current_db_revision()))
        if old_revision < self.get_current_db_revision():
            from lbry.extras.daemon.migrator import dbmigrator
            log.info("Upgrading your databases (revision %i to %i)", old_revision, self.get_current_db_revision())
            await asyncio.get_event_loop().run_in_executor(
                None, dbmigrator.migrate_db, self.conf, old_revision, self.get_current_db_revision()
            )
            self._write_db_revision_file(self.get_current_db_revision())
            log.info("Finished upgrading the databases.")

        self.storage = SQLiteStorage(
            self.conf, os.path.join(self.conf.data_dir, "lbrynet.sqlite")
        )
        await self.storage.open()

    async def stop(self):
        await self.storage.close()
        self.storage = None


class HeadersComponent(Component):
    component_name = HEADERS_COMPONENT
    HEADERS_URL = "https://headers.lbry.io/blockchain_headers_latest"
    CHECKPOINT = ('100b33ca3d0b86a48f0d6d6f30458a130ecb89d5affefe4afccb134d5a40f4c2', 600_000)

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.headers_dir = os.path.join(self.conf.wallet_dir, 'lbc_mainnet')
        self.headers_file = os.path.join(self.headers_dir, 'headers')
        self.old_file = os.path.join(self.conf.wallet_dir, 'blockchain_headers')
        self.headers = Headers(self.headers_file)
        self.is_downloading_headers = False
        self._headers_progress_percent = 0

    @property
    def component(self):
        return self

    def _round_progress(self, local_height, remote_height):
        return min(max(math.ceil(float(local_height) / float(remote_height) * 100), 0), 100)

    async def get_status(self) -> dict:
        progress = None
        if self.is_downloading_headers:
            progress = self._headers_progress_percent
        elif self.component_manager.has_component(WALLET_COMPONENT):
            wallet_manager = self.component_manager.get_component(WALLET_COMPONENT)
            if wallet_manager and wallet_manager.ledger.network.remote_height > 0:
                local_height = wallet_manager.ledger.headers.height
                remote_height = wallet_manager.ledger.network.remote_height
                progress = self._round_progress(local_height, remote_height)
        return {
            'downloading_headers': True,
            'download_progress': progress
        } if progress is not None and progress < 100 else {}

    async def fetch_headers_from_s3(self):
        local_header_size = self.local_header_file_size()
        resume_header = {"Range": f"bytes={local_header_size}-"}
        async with utils.aiohttp_request('get', self.HEADERS_URL, headers=resume_header) as response:
            if response.status == 406 or response.content_length < self.headers.header_size:  # our file is bigger
                log.warning("s3 is more out of date than we are")
                return
            final_size_after_download = response.content_length + local_header_size
            if final_size_after_download % self.headers.header_size != 0:
                log.warning("s3 appears to have corrupted header")
                return
            write_mode = "wb"
            if local_header_size > 0:
                log.info("Resuming download of %i bytes from s3", response.content_length)
                write_mode = "a+b"
            with open(self.headers_file, write_mode) as fd:
                while not response.content.at_eof():
                    local_header_size += fd.write(await response.content.readany())
                    self._headers_progress_percent = self._round_progress(
                        local_header_size, final_size_after_download
                    )

    def local_header_file_size(self) -> int:
        if os.path.isfile(self.headers_file):
            return os.stat(self.headers_file).st_size
        return 0

    async def get_downloadable_header_height(self) -> typing.Optional[int]:
        async with utils.aiohttp_request('HEAD', self.HEADERS_URL) as response:
            if response.status != 200:
                log.warning("Header download error, unexpected response code: %s", response.status)
                return -1
            return response.content_length // self.headers.header_size

    async def should_download_headers_from_s3(self) -> bool:
        if self.conf.blockchain_name != "lbrycrd_main":
            return False
        s3_headers_depth = self.conf.s3_headers_depth
        if not s3_headers_depth:
            return False

        local_height = self.local_header_file_size() // self.headers.header_size
        remote_height = await self.get_downloadable_header_height()
        if remote_height is not None:
            log.info("remote height: %i, local height: %i", remote_height, local_height)
            if remote_height > (local_height + s3_headers_depth):
                return True
        return False

    def verify_checkpoint(self):
        expected_hash, at_height = self.CHECKPOINT
        if self.local_header_file_size() // self.headers.header_size < at_height:
            return False
        hash = hashlib.sha256()
        chunk_size = self.headers.header_size * 1000
        with open(self.headers_file, 'rb') as header_file:
            data = header_file.read(chunk_size)
            while data and header_file.tell() <= at_height * self.headers.header_size:
                hash.update(data)
                data = header_file.read(chunk_size)
        return hash.hexdigest() == expected_hash

    async def start(self):
        if not os.path.exists(self.headers_dir):
            os.mkdir(self.headers_dir)
        if os.path.exists(self.old_file):
            log.warning("Moving old headers from %s to %s.", self.old_file, self.headers_file)
            os.rename(self.old_file, self.headers_file)

        try:
            if await self.should_download_headers_from_s3():
                self.is_downloading_headers = True
                await self.fetch_headers_from_s3()
        except Exception as err:
            log.error("failed to fetch headers from s3: %s", err)
        finally:
            self.is_downloading_headers = False
            # fixme: workaround, this should happen before download but happens after because headers.connect fail
            if not self.verify_checkpoint():
                log.info("Checkpoint failed, verifying headers using slower method.")
                await self.headers.open()
                await self.headers.repair()
                await self.headers.close()
    async def stop(self):
        pass


class WalletComponent(Component):
    component_name = WALLET_COMPONENT
    depends_on = [DATABASE_COMPONENT, HEADERS_COMPONENT]

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.wallet_manager = None

    @property
    def component(self):
        return self.wallet_manager

    async def get_status(self):
        if self.wallet_manager and self.wallet_manager.ledger.network.remote_height:
            local_height = self.wallet_manager.ledger.headers.height
            remote_height = self.wallet_manager.ledger.network.remote_height
            best_hash = self.wallet_manager.get_best_blockhash()
            return {
                'blocks': max(local_height, 0),
                'blocks_behind': max(remote_height - local_height, 0),
                'best_blockhash': best_hash,
                'is_encrypted': self.wallet_manager.use_encryption,
                'is_locked': not self.wallet_manager.is_wallet_unlocked,
            }

    async def start(self):
        log.info("Starting torba wallet")
        self.wallet_manager = await LbryWalletManager.from_lbrynet_config(self.conf)
        await self.wallet_manager.start()

    async def stop(self):
        await self.wallet_manager.stop()
        self.wallet_manager = None


class BlobComponent(Component):
    component_name = BLOB_COMPONENT
    depends_on = [DATABASE_COMPONENT]

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.blob_manager: typing.Optional[BlobManager] = None

    @property
    def component(self) -> typing.Optional[BlobManager]:
        return self.blob_manager

    async def start(self):
        storage = self.component_manager.get_component(DATABASE_COMPONENT)
        data_store = None
        if DHT_COMPONENT not in self.component_manager.skip_components:
            dht_node: Node = self.component_manager.get_component(DHT_COMPONENT)
            if dht_node:
                data_store = dht_node.protocol.data_store
        blob_dir = os.path.join(self.conf.data_dir, 'blobfiles')
        if not os.path.isdir(blob_dir):
            os.mkdir(blob_dir)
        self.blob_manager = BlobManager(self.component_manager.loop, blob_dir, storage, self.conf, data_store)
        return await self.blob_manager.setup()

    async def stop(self):
        self.blob_manager.stop()

    async def get_status(self):
        count = 0
        if self.blob_manager:
            count = len(self.blob_manager.completed_blob_hashes)
        return {
            'finished_blobs': count,
            'connections': {} if not self.blob_manager else self.blob_manager.connection_manager.status
        }


class DHTComponent(Component):
    component_name = DHT_COMPONENT
    depends_on = [UPNP_COMPONENT]

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.dht_node: typing.Optional[Node] = None
        self.external_udp_port = None
        self.external_peer_port = None

    @property
    def component(self) -> typing.Optional[Node]:
        return self.dht_node

    async def get_status(self):
        return {
            'node_id': None if not self.dht_node else binascii.hexlify(self.dht_node.protocol.node_id),
            'peers_in_routing_table': 0 if not self.dht_node else len(self.dht_node.protocol.routing_table.get_peers())
        }

    def get_node_id(self):
        node_id_filename = os.path.join(self.conf.data_dir, "node_id")
        if os.path.isfile(node_id_filename):
            with open(node_id_filename, "r") as node_id_file:
                return base58.b58decode(str(node_id_file.read()).strip())
        node_id = utils.generate_id()
        with open(node_id_filename, "w") as node_id_file:
            node_id_file.write(base58.b58encode(node_id).decode())
        return node_id

    async def start(self):
        log.info("start the dht")
        upnp_component = self.component_manager.get_component(UPNP_COMPONENT)
        self.external_peer_port = upnp_component.upnp_redirects.get("TCP", self.conf.tcp_port)
        self.external_udp_port = upnp_component.upnp_redirects.get("UDP", self.conf.udp_port)
        external_ip = upnp_component.external_ip
        if not external_ip:
            log.warning("UPnP component failed to get external ip")
            external_ip = await utils.get_external_ip()
            if not external_ip:
                log.warning("failed to get external ip")

        self.dht_node = Node(
            self.component_manager.loop,
            self.component_manager.peer_manager,
            node_id=self.get_node_id(),
            internal_udp_port=self.conf.udp_port,
            udp_port=self.external_udp_port,
            external_ip=external_ip,
            peer_port=self.external_peer_port,
            rpc_timeout=self.conf.node_rpc_timeout,
            split_buckets_under_index=self.conf.split_buckets_under_index
        )
        self.dht_node.start(
            interface=self.conf.network_interface, known_node_urls=self.conf.known_dht_nodes
        )
        log.info("Started the dht")

    async def stop(self):
        self.dht_node.stop()


class HashAnnouncerComponent(Component):
    component_name = HASH_ANNOUNCER_COMPONENT
    depends_on = [DHT_COMPONENT, DATABASE_COMPONENT]

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.hash_announcer: typing.Optional[BlobAnnouncer] = None

    @property
    def component(self) -> typing.Optional[BlobAnnouncer]:
        return self.hash_announcer

    async def start(self):
        storage = self.component_manager.get_component(DATABASE_COMPONENT)
        dht_node = self.component_manager.get_component(DHT_COMPONENT)
        self.hash_announcer = BlobAnnouncer(self.component_manager.loop, dht_node, storage)
        self.hash_announcer.start(self.conf.concurrent_blob_announcers)
        log.info("Started blob announcer")

    async def stop(self):
        self.hash_announcer.stop()
        log.info("Stopped blob announcer")

    async def get_status(self):
        return {
            'announce_queue_size': 0 if not self.hash_announcer else len(self.hash_announcer.announce_queue)
        }


class StreamManagerComponent(Component):
    component_name = STREAM_MANAGER_COMPONENT
    depends_on = [BLOB_COMPONENT, DATABASE_COMPONENT, WALLET_COMPONENT]

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.stream_manager: typing.Optional[StreamManager] = None

    @property
    def component(self) -> typing.Optional[StreamManager]:
        return self.stream_manager

    async def get_status(self):
        if not self.stream_manager:
            return
        return {
            'managed_files': len(self.stream_manager.streams),
        }

    async def start(self):
        blob_manager = self.component_manager.get_component(BLOB_COMPONENT)
        storage = self.component_manager.get_component(DATABASE_COMPONENT)
        wallet = self.component_manager.get_component(WALLET_COMPONENT)
        node = self.component_manager.get_component(DHT_COMPONENT)\
            if self.component_manager.has_component(DHT_COMPONENT) else None
        log.info('Starting the file manager')
        loop = asyncio.get_event_loop()
        self.stream_manager = StreamManager(
            loop, self.conf, blob_manager, wallet, storage, node, self.component_manager.analytics_manager
        )
        await self.stream_manager.start()
        log.info('Done setting up file manager')

    async def stop(self):
        self.stream_manager.stop()


class PeerProtocolServerComponent(Component):
    component_name = PEER_PROTOCOL_SERVER_COMPONENT
    depends_on = [UPNP_COMPONENT, BLOB_COMPONENT, WALLET_COMPONENT]

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.blob_server: typing.Optional[BlobServer] = None

    @property
    def component(self) -> typing.Optional[BlobServer]:
        return self.blob_server

    async def start(self):
        log.info("start blob server")
        upnp = self.component_manager.get_component(UPNP_COMPONENT)
        blob_manager: BlobManager = self.component_manager.get_component(BLOB_COMPONENT)
        wallet: LbryWalletManager = self.component_manager.get_component(WALLET_COMPONENT)
        peer_port = self.conf.tcp_port
        address = await wallet.get_unused_address()
        self.blob_server = BlobServer(asyncio.get_event_loop(), blob_manager, address)
        self.blob_server.start_server(peer_port, interface=self.conf.network_interface)
        await self.blob_server.started_listening.wait()

    async def stop(self):
        if self.blob_server:
            self.blob_server.stop_server()


class UPnPComponent(Component):
    component_name = UPNP_COMPONENT

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self._int_peer_port = self.conf.tcp_port
        self._int_dht_node_port = self.conf.udp_port
        self.use_upnp = self.conf.use_upnp
        self.upnp: typing.Optional[UPnP] = None
        self.upnp_redirects = {}
        self.external_ip: typing.Optional[str] = None
        self._maintain_redirects_task = None

    @property
    def component(self) -> 'UPnPComponent':
        return self

    async def _repeatedly_maintain_redirects(self, now=True):
        while True:
            if now:
                await self._maintain_redirects()
            await asyncio.sleep(360, loop=self.component_manager.loop)

    async def _maintain_redirects(self):
        # setup the gateway if necessary
        if not self.upnp:
            try:
                self.upnp = await UPnP.discover(loop=self.component_manager.loop)
                log.info("found upnp gateway: %s", self.upnp.gateway.manufacturer_string)
            except Exception as err:
                if isinstance(err, asyncio.CancelledError):
                    raise
                log.warning("upnp discovery failed: %s", err)
                self.upnp = None

        # update the external ip
        external_ip = None
        if self.upnp:
            try:
                external_ip = await self.upnp.get_external_ip()
                if external_ip != "0.0.0.0" and not self.external_ip:
                    log.info("got external ip from UPnP: %s", external_ip)
            except (asyncio.TimeoutError, UPnPError, NotImplementedError):
                pass

        if external_ip == "0.0.0.0" or (external_ip and external_ip.startswith("192.")):
            log.warning("unable to get external ip from UPnP, checking lbry.com fallback")
            external_ip = await utils.get_external_ip()
        if self.external_ip and self.external_ip != external_ip:
            log.info("external ip changed from %s to %s", self.external_ip, external_ip)
        if external_ip:
            self.external_ip = external_ip
        # assert self.external_ip is not None   # TODO: handle going/starting offline

        if not self.upnp_redirects and self.upnp:  # setup missing redirects
            log.info("add UPnP port mappings")
            upnp_redirects = {}
            if PEER_PROTOCOL_SERVER_COMPONENT not in self.component_manager.skip_components:
                try:
                    upnp_redirects["TCP"] = await self.upnp.get_next_mapping(
                        self._int_peer_port, "TCP", "LBRY peer port", self._int_peer_port
                    )
                except (UPnPError, asyncio.TimeoutError, NotImplementedError):
                    pass
            if DHT_COMPONENT not in self.component_manager.skip_components:
                try:
                    upnp_redirects["UDP"] = await self.upnp.get_next_mapping(
                        self._int_dht_node_port, "UDP", "LBRY DHT port", self._int_dht_node_port
                    )
                except (UPnPError, asyncio.TimeoutError, NotImplementedError):
                    pass
            if upnp_redirects:
                log.info("set up redirects: %s", upnp_redirects)
                self.upnp_redirects.update(upnp_redirects)
        elif self.upnp:  # check existing redirects are still active
            found = set()
            mappings = await self.upnp.get_redirects()
            for mapping in mappings:
                proto = mapping.protocol
                if proto in self.upnp_redirects and mapping.external_port == self.upnp_redirects[proto]:
                    if mapping.lan_address == self.upnp.lan_address:
                        found.add(proto)
            if 'UDP' not in found and DHT_COMPONENT not in self.component_manager.skip_components:
                try:
                    udp_port = await self.upnp.get_next_mapping(self._int_dht_node_port, "UDP", "LBRY DHT port")
                    self.upnp_redirects['UDP'] = udp_port
                    log.info("refreshed upnp redirect for dht port: %i", udp_port)
                except (asyncio.TimeoutError, UPnPError, NotImplementedError):
                    del self.upnp_redirects['UDP']
            if 'TCP' not in found and PEER_PROTOCOL_SERVER_COMPONENT not in self.component_manager.skip_components:
                try:
                    tcp_port = await self.upnp.get_next_mapping(self._int_peer_port, "TCP", "LBRY peer port")
                    self.upnp_redirects['TCP'] = tcp_port
                    log.info("refreshed upnp redirect for peer port: %i", tcp_port)
                except (asyncio.TimeoutError, UPnPError, NotImplementedError):
                    del self.upnp_redirects['TCP']
            if ('TCP' in self.upnp_redirects
                and PEER_PROTOCOL_SERVER_COMPONENT not in self.component_manager.skip_components) and (
                    'UDP' in self.upnp_redirects and DHT_COMPONENT not in self.component_manager.skip_components):
                if self.upnp_redirects:
                    log.debug("upnp redirects are still active")

    async def start(self):
        log.info("detecting external ip")
        if not self.use_upnp:
            self.external_ip = await utils.get_external_ip()
            return
        success = False
        await self._maintain_redirects()
        if self.upnp:
            if not self.upnp_redirects and not all([x in self.component_manager.skip_components for x in
                                                    (DHT_COMPONENT, PEER_PROTOCOL_SERVER_COMPONENT)]):
                log.error("failed to setup upnp")
            else:
                success = True
                if self.upnp_redirects:
                    log.debug("set up upnp port redirects for gateway: %s", self.upnp.gateway.manufacturer_string)
        else:
            log.error("failed to setup upnp")
        if self.component_manager.analytics_manager:
            await self.component_manager.analytics_manager.send_upnp_setup_success_fail(
                success, await self.get_status()
            )
        self._maintain_redirects_task = self.component_manager.loop.create_task(
            self._repeatedly_maintain_redirects(now=False)
        )

    async def stop(self):
        if self.upnp_redirects:
            log.info("Removing upnp redirects: %s", self.upnp_redirects)
            await asyncio.wait([
                self.upnp.delete_port_mapping(port, protocol) for protocol, port in self.upnp_redirects.items()
            ], loop=self.component_manager.loop)
        if self._maintain_redirects_task and not self._maintain_redirects_task.done():
            self._maintain_redirects_task.cancel()

    async def get_status(self):
        return {
            'aioupnp_version': aioupnp_version,
            'redirects': self.upnp_redirects,
            'gateway': 'No gateway found' if not self.upnp else self.upnp.gateway.manufacturer_string,
            'dht_redirect_set': 'UDP' in self.upnp_redirects,
            'peer_redirect_set': 'TCP' in self.upnp_redirects,
            'external_ip': self.external_ip
        }


class ExchangeRateManagerComponent(Component):
    component_name = EXCHANGE_RATE_MANAGER_COMPONENT

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.exchange_rate_manager = ExchangeRateManager()

    @property
    def component(self) -> ExchangeRateManager:
        return self.exchange_rate_manager

    async def start(self):
        self.exchange_rate_manager.start()

    async def stop(self):
        self.exchange_rate_manager.stop()
