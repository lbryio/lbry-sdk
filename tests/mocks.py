import io

from Crypto.PublicKey import RSA
from twisted.internet import defer, threads, task, error

from lbrynet.core import PTCWallet


class Node(object):
    def __init__(self, *args, **kwargs):
        pass

    def joinNetwork(self, *args):
        pass

    def stop(self):
        pass


class Wallet(object):
    def __init__(self):
        self.private_key = RSA.generate(1024)
        self.encoded_public_key = self.private_key.publickey().exportKey()

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

    def _generate_chunk(self, n=2**10):
        output = self.pattern[self.last_offset:self.last_offset + n]
        n_left = n - len(output)
        whole_patterns = n_left / len(self.pattern)
        output += self.pattern * whole_patterns
        self.last_offset = n - len(output)
        output += self.pattern[:self.last_offset]
        return output


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
