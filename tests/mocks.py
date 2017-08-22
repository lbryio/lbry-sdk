import io

from Crypto.PublicKey import RSA
from decimal import Decimal
from twisted.internet import defer

from lbrynet.core import PTCWallet
from lbrynet.core import BlobAvailability
from lbrynet.daemon import ExchangeRateManager as ERM
from lbrynet import conf

KB = 2**10


class FakeLBRYFile(object):
    def __init__(self, blob_manager, stream_info_manager, stream_hash, uri="fake_uri"):
        self.blob_manager = blob_manager
        self.stream_info_manager = stream_info_manager
        self.stream_hash = stream_hash
        self.name = "fake_uri"


class Node(object):
    def __init__(self, *args, **kwargs):
        pass

    def joinNetwork(self, *args):
        pass

    def stop(self):
        pass


class FakeNetwork(object):
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



class Wallet(object):
    def __init__(self):
        self.private_key = RSA.generate(1024)
        self.encoded_public_key = self.private_key.publickey().exportKey()
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
        return PTCWallet.PointTraderKeyExchanger(self)

    def get_wallet_info_query_handler_factory(self):
        return PTCWallet.PointTraderKeyQueryHandlerFactory(self)

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


class PeerFinder(object):
    def __init__(self, start_port, peer_manager, num_peers):
        self.start_port = start_port
        self.peer_manager = peer_manager
        self.num_peers = num_peers
        self.count = 0

    def find_peers_for_blob(self, *args):
        peer_port = self.start_port + self.count
        self.count += 1
        if self.count >= self.num_peers:
            self.count = 0
        return defer.succeed([self.peer_manager.get_peer("127.0.0.1", peer_port)])

    def run_manage_loop(self):
        pass

    def stop(self):
        pass


class Announcer(object):
    def __init__(self, *args):
        pass

    def hash_queue_size(self):
        return 0

    def add_supplier(self, supplier):
        pass

    def immediate_announce(self, *args):
        pass

    def run_manage_loop(self):
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
        whole_patterns = n_left / len(self.pattern)
        output += self.pattern * whole_patterns
        self.last_offset = size - len(output)
        output += self.pattern[:self.last_offset]
        return output


class BlobAvailabilityTracker(BlobAvailability.BlobAvailabilityTracker):
    """
    Class to track peer counts for known blobs, and to discover new popular blobs

    Attributes:
        availability (dict): dictionary of peers for known blobs
    """

    def __init__(self, blob_manager=None, peer_finder=None, dht_node=None):
        self.availability = {
            '91dc64cf1ff42e20d627b033ad5e4c3a4a96856ed8a6e3fb4cd5fa1cfba4bf72eefd325f579db92f45f4355550ace8e7': ['1.2.3.4'],
            'b2e48bb4c88cf46b76adf0d47a72389fae0cd1f19ed27dc509138c99509a25423a4cef788d571dca7988e1dca69e6fa0': ['1.2.3.4', '1.2.3.4'],
            '6af95cd062b4a179576997ef1054c9d2120f8592eea045e9667bea411d520262cd5a47b137eabb7a7871f5f8a79c92dd': ['1.2.3.4', '1.2.3.4', '1.2.3.4'],
            '6d8017aba362e5c5d0046625a039513419810a0397d728318c328a5cc5d96efb589fbca0728e54fe5adbf87e9545ee07': ['1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4'],
            '5a450b416275da4bdff604ee7b58eaedc7913c5005b7184fc3bc5ef0b1add00613587f54217c91097fc039ed9eace9dd': ['1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4'],
            'd7c82e6cac093b3f16107d2ae2b2c75424f1fcad2c7fbdbe66e4a13c0b6bd27b67b3a29c403b82279ab0f7c1c48d6787': ['1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4'],
            '9dbda74a472a2e5861a5d18197aeba0f5de67c67e401124c243d2f0f41edf01d7a26aeb0b5fc9bf47f6361e0f0968e2c': ['1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4'],
            '8c70d5e2f5c3a6085006198e5192d157a125d92e7378794472007a61947992768926513fc10924785bdb1761df3c37e6': ['1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4'],
            'f99d24cd50d4bfd77c2598bfbeeb8415bf0feef21200bdf0b8fbbde7751a77b7a2c68e09c25465a2f40fba8eecb0b4e0': ['1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4'],
            'c84aa1fd8f5009f7c4e71e444e40d95610abc1480834f835eefb267287aeb10025880a3ce22580db8c6d92efb5bc0c9c': ['1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4'],
        }
        self._blob_manager = None
        self._peer_finder = PeerFinder(11223, 11224, 2)
        self._dht_node = None
        self._check_popular = None
        self._check_mine = None
        self._set_mean_peers()

    def start(self):
        pass

    def stop(self):
        pass



create_stream_sd_file = {
    'stream_name': '746573745f66696c65',
    'blobs': [
        {
            'length': 2097152,
            'blob_num': 0,
            'blob_hash': 'dc4708f76a5e7af0f1cae0ee96b824e2ed9250c9346c093b441f0a20d3607c17948b6fcfb4bc62020fe5286693d08586',
            'iv': '30303030303030303030303030303031'
        },
        {
            'length': 2097152,
            'blob_num': 1,
            'blob_hash': 'f4067522c1b49432a2a679512e3917144317caa1abba0c041e0cd2cf9f635d4cf127ce1824fa04189b63916174951f70',
            'iv': '30303030303030303030303030303032'
        },
        {
            'length': 1015056,
            'blob_num': 2,
            'blob_hash': '305486c434260484fcb2968ce0e963b72f81ba56c11b08b1af0789b55b44d78422600f9a38e3cf4f2e9569897e5646a9',
            'iv': '30303030303030303030303030303033'
        },
        {'length': 0, 'blob_num': 3, 'iv': '30303030303030303030303030303034'}
    ],
    'stream_type': 'lbryfile',
    'key': '30313233343536373031323334353637',
    'suggested_file_name': '746573745f66696c65',
    'stream_hash': '6d27fbe10c86d81aacfb897c7a426d0a2214f5a299455a6d315c0f998c4b3545c2dc60906122d94653c23b1898229e3f'
}


def mock_conf_settings(obj, settings={}):
    original_settings = conf.settings
    conf.settings = conf.Config(conf.FIXED_SETTINGS, conf.ADJUSTABLE_SETTINGS)
    conf.settings.installation_id = conf.settings.get_installation_id()
    conf.settings.node_id = conf.settings.get_node_id()
    conf.settings.update(settings)

    def _reset_settings():
        conf.settings = original_settings

    obj.addCleanup(_reset_settings)



