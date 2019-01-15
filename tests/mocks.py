import asyncio
import base64
import io
from unittest import mock

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from twisted.internet import defer
from twisted.python.failure import Failure
from lbrynet import conf
from lbrynet.staging.old_blob_client import ClientRequest
from lbrynet.error import RequestCanceledError
from lbrynet.staging.EncryptedFileManager import EncryptedFileManager
from lbrynet.dht.node import Node as RealNode
from lbrynet.extras.daemon import ExchangeRateManager as ERM

KB = 2**10
PUBLIC_EXPONENT = 65537  # http://www.daemonology.net/blog/2009-06-11-cryptographic-right-answers.html


def decode_rsa_key(pem_key):
    decoded = base64.b64decode(''.join(pem_key.splitlines()[1:-1]))
    return serialization.load_der_public_key(decoded, default_backend())


class FakeLBRYFile:
    def __init__(self, blob_manager, stream_info_manager, stream_hash, uri="fake_uri"):
        self.blob_manager = blob_manager
        self.stream_info_manager = stream_info_manager
        self.stream_hash = stream_hash
        self.file_name = 'fake_lbry_file'


class Node(RealNode):
    def joinNetwork(self, known_node_addresses=None):
        return defer.succeed(None)

    def stop(self):
        return defer.succeed(None)

    def start(self, known_node_addresses=None):
        return self.joinNetwork(known_node_addresses)


class FakeNetwork:
    @staticmethod
    def get_local_height():
        return 1

    @staticmethod
    def get_server_height():
        return 1


class BTCLBCFeed(ERM.MarketFeed):
    def __init__(self):
        ERM.MarketFeed.__init__(
            self,
            "BTCLBC",
            "market name",
            "derp.com",
            None,
            0.0
        )


class USDBTCFeed(ERM.MarketFeed):
    def __init__(self):
        ERM.MarketFeed.__init__(
            self,
            "USDBTC",
            "market name",
            "derp.com",
            None,
            0.0
        )


class ExchangeRateManager(ERM.ExchangeRateManager):
    def __init__(self, market_feeds, rates):
        self.market_feeds = market_feeds
        for feed in self.market_feeds:
            feed.rate = ERM.ExchangeRate(
                feed.market, rates[feed.market]['spot'], rates[feed.market]['ts'])


class PointTraderKeyExchanger:

    def __init__(self, wallet):
        self.wallet = wallet
        self._protocols = []

    def send_next_request(self, peer, protocol):
        if not protocol in self._protocols:
            r = ClientRequest({'public_key': self.wallet.encoded_public_key.decode()},
                              'public_key')
            d = protocol.add_request(r)
            d.addCallback(self._handle_exchange_response, peer, r, protocol)
            d.addErrback(self._request_failed, peer)
            self._protocols.append(protocol)
            return defer.succeed(True)
        else:
            return defer.succeed(False)

    def _handle_exchange_response(self, response_dict, peer, request, protocol):
        assert request.response_identifier in response_dict, \
            "Expected %s in dict but did not get it" % request.response_identifier
        assert protocol in self._protocols, "Responding protocol is not in our list of protocols"
        peer_pub_key = response_dict[request.response_identifier]
        self.wallet.set_public_key_for_peer(peer, peer_pub_key)
        return True

    def _request_failed(self, err, peer):
        if not err.check(RequestCanceledError):
            return err


class PointTraderKeyQueryHandlerFactory:

    def __init__(self, wallet):
        self.wallet = wallet

    def build_query_handler(self):
        q_h = PointTraderKeyQueryHandler(self.wallet)
        return q_h

    def get_primary_query_identifier(self):
        return 'public_key'

    def get_description(self):
        return ("Point Trader Address - an address for receiving payments on the "
                "point trader testing network")


class PointTraderKeyQueryHandler:

    def __init__(self, wallet):
        self.wallet = wallet
        self.query_identifiers = ['public_key']
        self.public_key = None
        self.peer = None

    def register_with_request_handler(self, request_handler, peer):
        self.peer = peer
        request_handler.register_query_handler(self, self.query_identifiers)

    def handle_queries(self, queries):
        if self.query_identifiers[0] in queries:
            new_encoded_pub_key = queries[self.query_identifiers[0]]
            try:
                decode_rsa_key(new_encoded_pub_key)
            except (ValueError, TypeError, IndexError):
                raise ValueError(f"Client sent an invalid public key: {new_encoded_pub_key}")
            self.public_key = new_encoded_pub_key
            self.wallet.set_public_key_for_peer(self.peer, self.public_key)
            fields = {'public_key': self.wallet.encoded_public_key.decode()}
            return fields
        if self.public_key is None:
            raise ValueError("Expected but did not receive a public key")
        else:
            return {}


class Wallet:
    def __init__(self):
        self.private_key = rsa.generate_private_key(public_exponent=PUBLIC_EXPONENT,
                                                    key_size=1024, backend=default_backend())
        self.encoded_public_key = self.private_key.public_key().public_bytes(serialization.Encoding.PEM,
                                                                             serialization.PublicFormat.PKCS1)
        self._config = None
        self.network = None
        self.wallet = None
        self.is_first_run = False
        self.printed_retrieving_headers = False
        self._start_check = None
        self._catch_up_check = None
        self._caught_up_counter = 0
        self._lag_counter = 0
        self.blocks_behind = 0
        self.catchup_progress = 0
        self.max_behind = 0

    def start(self):
        return defer.succeed(True)

    def stop(self):
        return defer.succeed(True)

    def get_info_exchanger(self):
        return PointTraderKeyExchanger(self)

    def update_peer_address(self, peer, address):
        pass

    def get_wallet_info_query_handler_factory(self):
        return PointTraderKeyQueryHandlerFactory(self)

    def get_unused_address_for_peer(self, peer):
        return defer.succeed("bDtL6qriyimxz71DSYjojTBsm6cpM1bqmj")

    def reserve_points(self, *args):
        return True

    def cancel_point_reservation(self, *args):
        pass

    def send_points(self, *args):
        return defer.succeed(True)

    def add_expected_payment(self, *args):
        pass

    def get_balance(self):
        return defer.succeed(1000)

    def set_public_key_for_peer(self, peer, public_key):
        pass

    def get_claim_metadata_for_sd_hash(self, sd_hash):
        return "fakeuri", "aa04a949348f9f094d503e5816f0cfb57ee68a22f6d08d149217d071243e0377", 1

    def get_claimid(self, name, txid=None, nout=None):
        return "aa04a949348f9f094d503e5816f0cfb57ee68a22f6d08d149217d071243e0378"


class PeerFinder:
    def __init__(self, start_port, peer_manager, num_peers):
        self.start_port = start_port
        self.peer_manager = peer_manager
        self.num_peers = num_peers
        self.count = 0

    def find_peers_for_blob(self, h, filter_self=False):
        peer_port = self.start_port + self.count
        self.count += 1
        if self.count >= self.num_peers:
            self.count = 0
        return defer.succeed([self.peer_manager.get_peer("127.0.0.1", tcp_port=peer_port)])

    def run_manage_loop(self):
        pass

    def stop(self):
        pass


class Announcer:
    def __init__(self, *args):
        pass

    def hash_queue_size(self):
        return 0

    def immediate_announce(self, *args):
        pass

    def start(self):
        pass

    def stop(self):
        pass


class GenFile(io.RawIOBase):
    def __init__(self, size, pattern):
        io.RawIOBase.__init__(self)
        self.size = size
        self.pattern = pattern
        self.read_so_far = 0
        self.buff = b''
        self.last_offset = 0
        self.name = "."

    def readable(self):
        return True

    def writable(self):
        return False

    def read(self, n=-1):
        if n > -1:
            bytes_to_read = min(n, self.size - self.read_so_far)
        else:
            bytes_to_read = self.size - self.read_so_far
        output, self.buff = self.buff[:bytes_to_read], self.buff[bytes_to_read:]
        bytes_to_read -= len(output)
        while bytes_to_read > 0:
            self.buff = self._generate_chunk()
            new_output, self.buff = self.buff[:bytes_to_read], self.buff[bytes_to_read:]
            bytes_to_read -= len(new_output)
            output += new_output
        self.read_so_far += len(output)
        return output

    def readall(self):
        return self.read()

    def _generate_chunk(self, size=KB):
        output = self.pattern[self.last_offset:self.last_offset + size]
        n_left = size - len(output)
        whole_patterns = n_left // len(self.pattern)
        output += self.pattern * whole_patterns
        self.last_offset = size - len(output)
        output += self.pattern[:self.last_offset]
        return output


# The components below viz. FakeWallet, FakeSession, FakeFileManager are just for testing Component Manager's
# startup and stop
class FakeComponent:
    depends_on = []
    component_name = None

    def __init__(self, component_manager):
        self.component_manager = component_manager
        self._running = False

    @property
    def running(self):
        return self._running

    async def start(self):
        pass

    async def stop(self):
        pass

    @property
    def component(self):
        return self

    async def _setup(self):
        result = await self.start()
        self._running = True
        return result

    async def _stop(self):
        result = await self.stop()
        self._running = False
        return result

    async def get_status(self):
        return {}

    def __lt__(self, other):
        return self.component_name < other.component_name


class FakeDelayedWallet(FakeComponent):
    component_name = "wallet"
    depends_on = []

    async def stop(self):
        await asyncio.sleep(1)


class FakeDelayedBlobManager(FakeComponent):
    component_name = "blob_manager"
    depends_on = [FakeDelayedWallet.component_name]

    async def start(self):
        await asyncio.sleep(1)

    async def stop(self):
        await asyncio.sleep(1)


class FakeDelayedFileManager(FakeComponent):
    component_name = "file_manager"
    depends_on = [FakeDelayedBlobManager.component_name]

    async def start(self):
        await asyncio.sleep(1)


class FakeFileManager(FakeComponent):
    component_name = "file_manager"
    depends_on = []

    @property
    def component(self):
        return mock.Mock(spec=EncryptedFileManager)


create_stream_sd_file = {
    'stream_name': '746573745f66696c65',
    'blobs': [
        {
            'length': 2097152,
            'blob_num': 0,
            'blob_hash': 'dc4708f76a5e7af0f1cae0ee96b824e2ed9250c9346c093b'
                         '441f0a20d3607c17948b6fcfb4bc62020fe5286693d08586',
            'iv': '30303030303030303030303030303031'
        },
        {
            'length': 2097152,
            'blob_num': 1,
            'blob_hash': 'f4067522c1b49432a2a679512e3917144317caa1abba0c04'
                         '1e0cd2cf9f635d4cf127ce1824fa04189b63916174951f70',
            'iv': '30303030303030303030303030303032'
        },
        {
            'length': 1015056,
            'blob_num': 2,
            'blob_hash': '305486c434260484fcb2968ce0e963b72f81ba56c11b08b1'
                         'af0789b55b44d78422600f9a38e3cf4f2e9569897e5646a9',
            'iv': '30303030303030303030303030303033'
        },
        {'length': 0, 'blob_num': 3, 'iv': '30303030303030303030303030303034'}
    ],
    'stream_type': 'lbryfile',
    'key': '30313233343536373031323334353637',
    'suggested_file_name': '746573745f66696c65',
    'stream_hash': '6d27fbe10c86d81aacfb897c7a426d0a2214f5a299455a6d'
                   '315c0f998c4b3545c2dc60906122d94653c23b1898229e3f'
}


def mock_conf_settings(obj, settings={}):
    conf.settings = None
    settings.setdefault('download_mirrors', [])
    conf.initialize_settings(False)
    original_settings = conf.settings
    conf.settings = conf.Config(conf.FIXED_SETTINGS, conf.ADJUSTABLE_SETTINGS)
    conf.settings['data_dir'] = settings.get('data_dir') or conf.settings.data_dir \
                                or conf.settings.default_data_dir
    conf.settings['download_directory'] = settings.get('download_directory') or conf.settings.download_dir \
                                    or conf.settings.default_download_dir
    conf.settings['wallet_dir'] = settings.get('wallet_dir') or conf.settings.wallet_dir or \
                                  conf.settings.default_wallet_dir
    conf.settings.installation_id = conf.settings.get_installation_id()
    conf.settings.node_id = conf.settings.get_node_id()
    conf.settings.update(settings)

    def _reset_settings():
        conf.settings = original_settings

    obj.addCleanup(_reset_settings)
