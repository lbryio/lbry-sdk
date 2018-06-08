import os
import hashlib
import struct
from binascii import hexlify, unhexlify
from typing import List, Dict, Type
from operator import itemgetter

from twisted.internet import threads, defer, task, reactor

from torba import basetransaction, basedatabase
from torba.account import Account, AccountsView
from torba.basecoin import BaseCoin
from torba.basenetwork import BaseNetwork
from torba.stream import StreamController, execute_serially
from torba.util import int_to_hex, rev_hex, hash_encode
from torba.hash import double_sha256, pow_hash


class Address:

    def __init__(self, pubkey_hash):
        self.pubkey_hash = pubkey_hash
        self.transactions = []  # type: List[BaseTransaction]

    def __iter__(self):
        return iter(self.transactions)

    def __len__(self):
        return len(self.transactions)

    def add_transaction(self, transaction):
        if transaction not in self.transactions:
            self.transactions.append(transaction)


class BaseLedger(object):

    # coin_class is automatically set by BaseCoin metaclass
    # when it creates the Coin classes, there is a 1..1 relationship
    # between a coin and a ledger (at the class level) but a 1..* relationship
    # at instance level. Only one Ledger instance should exist per coin class,
    # but many coin instances can exist linking back to the single Ledger instance.
    coin_class = None  # type: Type[BaseCoin]
    network_class = None  # type: Type[BaseNetwork]
    headers_class = None  # type: Type[BaseHeaders]
    database_class = None  # type: Type[basedatabase.BaseSQLiteWalletStorage]

    default_fee_per_byte = 10

    def __init__(self, accounts, config=None, db=None, network=None,
                 fee_per_byte=default_fee_per_byte):
        self.accounts = accounts  # type: AccountsView
        self.config = config or {}
        self.db = db or self.database_class(self)  # type: basedatabase.BaseSQLiteWalletStorage
        self.network = network or self.network_class(self)
        self.network.on_header.listen(self.process_header)
        self.network.on_status.listen(self.process_status)
        self.headers = self.headers_class(self)
        self.fee_per_byte = fee_per_byte

        self._on_transaction_controller = StreamController()
        self.on_transaction = self._on_transaction_controller.stream

    @property
    def path(self):
        return os.path.join(
            self.config['wallet_path'], self.coin_class.get_id()
        )

    def get_input_output_fee(self, io):
        """ Fee based on size of the input / output. """
        return self.fee_per_byte * io.size

    def get_transaction_base_fee(self, tx):
        """ Fee for the transaction header and all outputs; without inputs. """
        return self.fee_per_byte * tx.base_size

    @property
    def transaction_class(self):
        return self.coin_class.transaction_class

    @classmethod
    def from_json(cls, json_dict):
        return cls(json_dict)

    @defer.inlineCallbacks
    def is_address_old(self, address, age_limit=2):
        height = yield self.db.get_earliest_block_height_for_address(address)
        if height is None:
            return False
        age = self.headers.height - height + 1
        return age > age_limit

    @defer.inlineCallbacks
    def add_transaction(self, transaction, height):  # type: (basetransaction.BaseTransaction, int) -> None
        yield self.db.add_transaction(transaction, height, False, False)
        self._on_transaction_controller.add(transaction)

    def has_address(self, address):
        return address in self.accounts.addresses

    @defer.inlineCallbacks
    def get_least_used_address(self, account, keychain, max_transactions=100):
        used_addresses = yield self.db.get_used_addresses(account)
        unused_set = set(keychain.addresses) - set(map(itemgetter(0), used_addresses))
        if unused_set:
            defer.returnValue(unused_set.pop())
        if used_addresses and used_addresses[0][1] < max_transactions:
            defer.returnValue(used_addresses[0][0])

    def get_unspent_outputs(self, account):
        return self.db.get_utxos(account, self.transaction_class.output_class)

#    def get_unspent_outputs(self, account):
#        inputs, outputs, utxos = set(), set(), set()
#        for address in self.addresses.values():
#            for tx in address:
#                for txi in tx.inputs:
#                    inputs.add((hexlify(txi.output_txid), txi.output_index))
#                for txo in tx.outputs:
#                    if txo.script.is_pay_pubkey_hash and txo.script.values['pubkey_hash'] == address.pubkey_hash:
#                        outputs.add((txo, txo.transaction.id, txo.index))
#        for output in outputs:
#            if output[1:] not in inputs:
#                yield output[0]

    @defer.inlineCallbacks
    def start(self):
        if not os.path.exists(self.path):
            os.mkdir(self.path)
        yield self.db.start()
        first_connection = self.network.on_connected.first
        self.network.start()
        yield first_connection
        self.headers.touch()
        yield self.update_headers()
        yield self.network.subscribe_headers()
        yield self.update_accounts()

    def stop(self):
        return self.network.stop()

    @execute_serially
    @defer.inlineCallbacks
    def update_headers(self):
        while True:
            height_sought = len(self.headers)
            headers = yield self.network.get_headers(height_sought)
            print("received {} headers starting at {} height".format(headers['count'], height_sought))
            #log.info("received {} headers starting at {} height".format(headers['count'], height_sought))
            if headers['count'] <= 0:
                break
            yield self.headers.connect(height_sought, unhexlify(headers['hex']))

    @defer.inlineCallbacks
    def process_header(self, response):
        header = response[0]
        if self.update_headers.is_running:
            return
        if header['height'] == len(self.headers):
            # New header from network directly connects after the last local header.
            yield self.headers.connect(len(self.headers), unhexlify(header['hex']))
        elif header['height'] > len(self.headers):
            # New header is several heights ahead of local, do download instead.
            yield self.update_headers()

    @execute_serially
    def update_accounts(self):
        return defer.DeferredList([
            self.update_account(a) for a in self.accounts
        ])

    @defer.inlineCallbacks
    def update_account(self, account):  # type: (Account) -> defer.Defferred
        # Before subscribing, download history for any addresses that don't have any,
        # this avoids situation where we're getting status updates to addresses we know
        # need to update anyways. Continue to get history and create more addresses until
        # all missing addresses are created and history for them is fully restored.
        yield account.ensure_enough_addresses()
        used_addresses = yield self.db.get_used_addresses(account)
        addresses = set(account.addresses) - set(map(itemgetter(0), used_addresses))
        while addresses:
            yield defer.DeferredList([
                self.update_history(a) for a in addresses
            ])
            addresses = yield account.ensure_enough_addresses()

        # By this point all of the addresses should be restored and we
        # can now subscribe all of them to receive updates.
        yield defer.DeferredList([
            self.subscribe_history(address)
            for address in account.addresses
        ])

    def _get_status_from_history(self, history):
        hashes = [
            '{}:{}:'.format(hash.decode(), height).encode()
            for hash, height in map(itemgetter('tx_hash', 'height'), history)
        ]
        if hashes:
            return hexlify(hashlib.sha256(b''.join(hashes)).digest())

    @defer.inlineCallbacks
    def update_history(self, address, remote_status=None):
        history = yield self.network.get_history(address)
        for hash, height in map(itemgetter('tx_hash', 'height'), history):
            if not (yield self.db.has_transaction(hash)):
                raw = yield self.network.get_transaction(hash)
                transaction = self.transaction_class(unhexlify(raw))
                yield self.add_transaction(transaction, height)
        if remote_status is None:
            remote_status = self._get_status_from_history(history)
        if remote_status:
            yield self.db.set_address_status(address, remote_status)

    @defer.inlineCallbacks
    def subscribe_history(self, address):
        remote_status = yield self.network.subscribe_address(address)
        local_status = yield self.db.get_address_status(address)
        if local_status != remote_status:
            yield self.update_history(address, remote_status)

    @defer.inlineCallbacks
    def process_status(self, response):
        address, remote_status = response
        local_status = yield self.db.get_address_status(address)
        if local_status != remote_status:
            yield self.update_history(address, remote_status)

    def broadcast(self, tx):
        return self.network.broadcast(hexlify(tx.raw))


class BaseHeaders:

    header_size = 80
    verify_bits_to_target = True

    def __init__(self, ledger):
        self.ledger = ledger
        self._size = None
        self._on_change_controller = StreamController()
        self.on_changed = self._on_change_controller.stream

    @property
    def path(self):
        return os.path.join(self.ledger.path, 'headers')

    def touch(self):
        if not os.path.exists(self.path):
            with open(self.path, 'wb'):
                pass

    @property
    def height(self):
        return len(self) - 1

    def sync_read_length(self):
        return os.path.getsize(self.path) // self.header_size

    def sync_read_header(self, height):
        if 0 <= height < len(self):
            with open(self.path, 'rb') as f:
                f.seek(height * self.header_size)
                return f.read(self.header_size)

    def __len__(self):
        if self._size is None:
            self._size = self.sync_read_length()
        return self._size

    def __getitem__(self, height):
        assert not isinstance(height, slice),\
            "Slicing of header chain has not been implemented yet."
        header = self.sync_read_header(height)
        return self._deserialize(height, header)

    @execute_serially
    @defer.inlineCallbacks
    def connect(self, start, headers):
        yield threads.deferToThread(self._sync_connect, start, headers)

    def _sync_connect(self, start, headers):
        previous_header = None
        for header in self._iterate_headers(start, headers):
            height = header['block_height']
            if previous_header is None and height > 0:
                previous_header = self[height-1]
            self._verify_header(height, header, previous_header)
            previous_header = header

        with open(self.path, 'r+b') as f:
            f.seek(start * self.header_size)
            f.write(headers)
            f.truncate()

        _old_size = self._size
        self._size = self.sync_read_length()
        change = self._size - _old_size
        #log.info('saved {} header blocks'.format(change))
        self._on_change_controller.add(change)

    def _iterate_headers(self, height, headers):
        assert len(headers) % self.header_size == 0
        for idx in range(len(headers) // self.header_size):
            start, end = idx * self.header_size, (idx + 1) * self.header_size
            header = headers[start:end]
            yield self._deserialize(height+idx, header)

    def _verify_header(self, height, header, previous_header):
        previous_hash = self._hash_header(previous_header)
        assert previous_hash == header['prev_block_hash'], \
            "prev hash mismatch: {} vs {}".format(previous_hash, header['prev_block_hash'])

        bits, target = self._calculate_next_work_required(height, previous_header, header)
        assert bits == header['bits'], \
            "bits mismatch: {} vs {} (hash: {})".format(
            bits, header['bits'], self._hash_header(header))

        # TODO: FIX ME!!!
        #_pow_hash = self._pow_hash_header(header)
        #assert int(b'0x' + _pow_hash, 16) <= target, \
        #    "insufficient proof of work: {} vs target {}".format(
        #    int(b'0x' + _pow_hash, 16), target)

    @staticmethod
    def _serialize(header):
        return b''.join([
            int_to_hex(header['version'], 4),
            rev_hex(header['prev_block_hash']),
            rev_hex(header['merkle_root']),
            int_to_hex(int(header['timestamp']), 4),
            int_to_hex(int(header['bits']), 4),
            int_to_hex(int(header['nonce']), 4)
        ])

    @staticmethod
    def _deserialize(height, header):
        version, = struct.unpack('<I', header[:4])
        timestamp, bits, nonce = struct.unpack('<III', header[68:80])
        return {
            'block_height': height,
            'version': version,
            'prev_block_hash': hash_encode(header[4:36]),
            'merkle_root': hash_encode(header[36:68]),
            'timestamp': timestamp,
            'bits': bits,
            'nonce': nonce,
        }

    def _hash_header(self, header):
        if header is None:
            return b'0' * 64
        return hash_encode(double_sha256(unhexlify(self._serialize(header))))

    def _pow_hash_header(self, header):
        if header is None:
            return b'0' * 64
        return hash_encode(pow_hash(unhexlify(self._serialize(header))))

    def _calculate_next_work_required(self, height, first, last):

        if height == 0:
            return self.ledger.genesis_bits, self.ledger.max_target

        if self.verify_bits_to_target:
            bits = last['bits']
            bitsN = (bits >> 24) & 0xff
            assert 0x03 <= bitsN <= 0x1d, \
                "First part of bits should be in [0x03, 0x1d], but it was {}".format(hex(bitsN))
            bitsBase = bits & 0xffffff
            assert 0x8000 <= bitsBase <= 0x7fffff, \
                "Second part of bits should be in [0x8000, 0x7fffff] but it was {}".format(bitsBase)

        # new target
        retargetTimespan = self.ledger.target_timespan
        nActualTimespan = last['timestamp'] - first['timestamp']

        nModulatedTimespan = retargetTimespan + (nActualTimespan - retargetTimespan) // 8

        nMinTimespan = retargetTimespan - (retargetTimespan // 8)
        nMaxTimespan = retargetTimespan + (retargetTimespan // 2)

        # Limit adjustment step
        if nModulatedTimespan < nMinTimespan:
            nModulatedTimespan = nMinTimespan
        elif nModulatedTimespan > nMaxTimespan:
            nModulatedTimespan = nMaxTimespan

        # Retarget
        bnPowLimit = _ArithUint256(self.ledger.max_target)
        bnNew = _ArithUint256.SetCompact(last['bits'])
        bnNew *= nModulatedTimespan
        bnNew //= nModulatedTimespan
        if bnNew > bnPowLimit:
            bnNew = bnPowLimit

        return bnNew.GetCompact(), bnNew._value


class _ArithUint256:
    """ See: lbrycrd/src/arith_uint256.cpp """

    def __init__(self, value):
        self._value = value

    def __str__(self):
        return hex(self._value)

    @staticmethod
    def fromCompact(nCompact):
        """Convert a compact representation into its value"""
        nSize = nCompact >> 24
        # the lower 23 bits
        nWord = nCompact & 0x007fffff
        if nSize <= 3:
            return nWord >> 8 * (3 - nSize)
        else:
            return nWord << 8 * (nSize - 3)

    @classmethod
    def SetCompact(cls, nCompact):
        return cls(cls.fromCompact(nCompact))

    def bits(self):
        """Returns the position of the highest bit set plus one."""
        bn = bin(self._value)[2:]
        for i, d in enumerate(bn):
            if d:
                return (len(bn) - i) + 1
        return 0

    def GetLow64(self):
        return self._value & 0xffffffffffffffff

    def GetCompact(self):
        """Convert a value into its compact representation"""
        nSize = (self.bits() + 7) // 8
        nCompact = 0
        if nSize <= 3:
            nCompact = self.GetLow64() << 8 * (3 - nSize)
        else:
            bn = _ArithUint256(self._value >> 8 * (nSize - 3))
            nCompact = bn.GetLow64()
        # The 0x00800000 bit denotes the sign.
        # Thus, if it is already set, divide the mantissa by 256 and increase the exponent.
        if nCompact & 0x00800000:
            nCompact >>= 8
            nSize += 1
        assert (nCompact & ~0x007fffff) == 0
        assert nSize < 256
        nCompact |= nSize << 24
        return nCompact

    def __mul__(self, x):
        # Take the mod because we are limited to an unsigned 256 bit number
        return _ArithUint256((self._value * x) % 2 ** 256)

    def __ifloordiv__(self, x):
        self._value = (self._value // x)
        return self

    def __gt__(self, x):
        return self._value > x._value
