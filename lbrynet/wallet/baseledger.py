import os
import logging
import hashlib
from binascii import hexlify
from typing import List, Dict, Type
from binascii import unhexlify
from operator import itemgetter

from twisted.internet import threads, defer

from lbrynet.wallet.account import Account, AccountsView
from lbrynet.wallet.basecoin import BaseCoin
from lbrynet.wallet.basetransaction import BaseTransaction, BaseInput, BaseOutput
from lbrynet.wallet.basenetwork import BaseNetwork
from lbrynet.wallet.stream import StreamController, execute_serially
from lbrynet.wallet.util import hex_to_int, int_to_hex, rev_hex, hash_encode
from lbrynet.wallet.hash import double_sha256, pow_hash

log = logging.getLogger(__name__)


class Address:

    def __init__(self, pubkey_hash):
        self.pubkey_hash = pubkey_hash
        self.transactions = []  # type: List[BaseTransaction]

    def __iter__(self):
        return iter(self.transactions)

    def __len__(self):
        return len(self.transactions)

    def add_transaction(self, transaction):
        self.transactions.append(transaction)

    def get_unspent_utxos(self):
        inputs, outputs, utxos = [], [], []
        for tx in self:
            for txi in tx.inputs:
                inputs.append((txi.output_txid, txi.output_index))
            for txo in tx.outputs:
                if txo.script.is_pay_pubkey_hash and txo.script.values['pubkey_hash'] == self.pubkey_hash:
                    outputs.append((txo, txo.transaction.hash, txo.index))
        for output in set(outputs):
            if output[1:] not in inputs:
                yield output[0]


class BaseLedger:

    # coin_class is automatically set by BaseCoin metaclass
    # when it creates the Coin classes, there is a 1..1 relationship
    # between a coin and a ledger (at the class level) but a 1..* relationship
    # at instance level. Only one Ledger instance should exist per coin class,
    # but many coin instances can exist linking back to the single Ledger instance.
    coin_class = None  # type: Type[BaseCoin]
    network_class = None  # type: Type[BaseNetwork]

    verify_bits_to_target = True

    def __init__(self, accounts, config=None, network=None, db=None):
        self.accounts = accounts  # type: AccountsView
        self.config = config or {}
        self.db = db
        self.addresses = {}  # type: Dict[str, Address]
        self.transactions = {}  # type: Dict[str, BaseTransaction]
        self.headers = Headers(self)
        self._on_transaction_controller = StreamController()
        self.on_transaction = self._on_transaction_controller.stream
        self.network = network or self.network_class(self.config)
        self.network.on_header.listen(self.process_header)
        self.network.on_status.listen(self.process_status)

    @property
    def transaction_class(self):
        return self.coin_class.transaction_class

    @classmethod
    def from_json(cls, json_dict):
        return cls(json_dict)

    @defer.inlineCallbacks
    def load(self):
        txs = yield self.db.get_transactions()
        for tx_hash, raw, height in txs:
            self.transactions[tx_hash] = self.transaction_class(raw, height)
        txios = yield self.db.get_transaction_inputs_and_outputs()
        for tx_hash, address_hash, input_output, amount, height in txios:
            tx = self.transactions[tx_hash]
            address = self.addresses.get(address_hash)
            if address is None:
                address = self.addresses[address_hash] = Address(self.coin_class.address_to_hash160(address_hash))
            tx.add_txio(address, input_output, amount)
            address.add_transaction(tx)

    def is_address_old(self, address, age_limit=2):
        age = -1
        for tx in self.get_transactions(address, []):
            if tx.height == 0:
                tx_age = 0
            else:
                tx_age = self.headers.height - tx.height + 1
            if tx_age > age:
                age = tx_age
        return age > age_limit

    def add_transaction(self, address, transaction):  # type: (str, BaseTransaction) -> None
        if address not in self.addresses:
            self.addresses[address] = Address(self.coin_class.address_to_hash160(address))
        self.addresses[address].add_transaction(transaction)
        self.transactions.setdefault(hexlify(transaction.id), transaction)
        self._on_transaction_controller.add(transaction)

    def has_address(self, address):
        return address in self.addresses

    def get_transaction(self, tx_hash, *args):
        return self.transactions.get(tx_hash, *args)

    def get_transactions(self, address, *args):
        return self.addresses.get(address, *args)

    def get_status(self, address):
        hashes = [
            '{}:{}:'.format(tx.hash, tx.height)
            for tx in self.get_transactions(address, [])
        ]
        if hashes:
            return hashlib.sha256(''.join(hashes)).digest().encode('hex')

    def has_transaction(self, tx_hash):
        return tx_hash in self.transactions

    def get_least_used_address(self, addresses, max_transactions=100):
        transaction_counts = []
        for address in addresses:
            transactions = self.get_transactions(address, [])
            tx_count = len(transactions)
            if tx_count == 0:
                return address
            elif tx_count >= max_transactions:
                continue
            else:
                transaction_counts.append((address, tx_count))
        if transaction_counts:
            transaction_counts.sort(key=itemgetter(1))
            return transaction_counts[0]

    def get_unspent_outputs(self, address):
        if address in self.addresses:
            return list(self.addresses[address].get_unspent_utxos())
        return []

    @defer.inlineCallbacks
    def start(self):
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
            log.info("received {} headers starting at {} height".format(headers['count'], height_sought))
            if headers['count'] <= 0:
                break
            yield self.headers.connect(height_sought, headers['hex'].decode('hex'))

    @defer.inlineCallbacks
    def process_header(self, response):
        header = response[0]
        if self.update_headers.is_running:
            return
        if header['height'] == len(self.headers):
            # New header from network directly connects after the last local header.
            yield self.headers.connect(len(self.headers), header['hex'].decode('hex'))
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
        account.ensure_enough_addresses()
        addresses = list(account.addresses_without_history())
        while addresses:
            yield defer.DeferredList([
                self.update_history(a) for a in addresses
            ])
            addresses = account.ensure_enough_addresses()

        # By this point all of the addresses should be restored and we
        # can now subscribe all of them to receive updates.
        yield defer.DeferredList([
            self.subscribe_history(address)
            for address in account.addresses
        ])

    @defer.inlineCallbacks
    def update_history(self, address):
        history = yield self.network.get_history(address)
        for hash in map(itemgetter('tx_hash'), history):
            transaction = self.get_transaction(hash)
            if not transaction:
                raw = yield self.network.get_transaction(hash)
                transaction = self.transaction_class(unhexlify(raw))
            self.add_transaction(address, transaction)

    @defer.inlineCallbacks
    def subscribe_history(self, address):
        status = yield self.network.subscribe_address(address)
        if status != self.get_status(address):
            self.update_history(address)

    def process_status(self, response):
        address, status = response
        if status != self.get_status(address):
            self.update_history(address)


class Headers:

    def __init__(self, ledger):
        self.ledger = ledger
        self._size = None
        self._on_change_controller = StreamController()
        self.on_changed = self._on_change_controller.stream

    @property
    def path(self):
        wallet_path = self.ledger.config.get('wallet_path', '')
        filename = '{}_headers'.format(self.ledger.coin_class.get_id())
        return os.path.join(wallet_path, filename)

    def touch(self):
        if not os.path.exists(self.path):
            with open(self.path, 'wb'):
                pass

    @property
    def height(self):
        return len(self) - 1

    def sync_read_length(self):
        return os.path.getsize(self.path) / self.ledger.header_size

    def sync_read_header(self, height):
        if 0 <= height < len(self):
            with open(self.path, 'rb') as f:
                f.seek(height * self.ledger.header_size)
                return f.read(self.ledger.header_size)

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
            f.seek(start * self.ledger.header_size)
            f.write(headers)
            f.truncate()

        _old_size = self._size
        self._size = self.sync_read_length()
        change = self._size - _old_size
        log.info('saved {} header blocks'.format(change))
        self._on_change_controller.add(change)

    def _iterate_headers(self, height, headers):
        assert len(headers) % self.ledger.header_size == 0
        for idx in range(len(headers) / self.ledger.header_size):
            start, end = idx * self.ledger.header_size, (idx + 1) * self.ledger.header_size
            header = headers[start:end]
            yield self._deserialize(height+idx, header)

    def _verify_header(self, height, header, previous_header):
        previous_hash = self._hash_header(previous_header)
        assert previous_hash == header['prev_block_hash'], \
            "prev hash mismatch: {} vs {}".format(previous_hash, header['prev_block_hash'])

        bits, target = self._calculate_lbry_next_work_required(height, previous_header, header)
        assert bits == header['bits'], \
            "bits mismatch: {} vs {} (hash: {})".format(
            bits, header['bits'], self._hash_header(header))

        _pow_hash = self._pow_hash_header(header)
        assert int('0x' + _pow_hash, 16) <= target, \
            "insufficient proof of work: {} vs target {}".format(
            int('0x' + _pow_hash, 16), target)

    @staticmethod
    def _serialize(header):
        return ''.join([
            int_to_hex(header['version'], 4),
            rev_hex(header['prev_block_hash']),
            rev_hex(header['merkle_root']),
            rev_hex(header['claim_trie_root']),
            int_to_hex(int(header['timestamp']), 4),
            int_to_hex(int(header['bits']), 4),
            int_to_hex(int(header['nonce']), 4)
        ])

    @staticmethod
    def _deserialize(height, header):
        return {
            'version': hex_to_int(header[0:4]),
            'prev_block_hash': hash_encode(header[4:36]),
            'merkle_root': hash_encode(header[36:68]),
            'claim_trie_root': hash_encode(header[68:100]),
            'timestamp': hex_to_int(header[100:104]),
            'bits': hex_to_int(header[104:108]),
            'nonce': hex_to_int(header[108:112]),
            'block_height': height
        }

    def _hash_header(self, header):
        if header is None:
            return '0' * 64
        return hash_encode(double_sha256(self._serialize(header).decode('hex')))

    def _pow_hash_header(self, header):
        if header is None:
            return '0' * 64
        return hash_encode(pow_hash(self._serialize(header).decode('hex')))

    def _calculate_lbry_next_work_required(self, height, first, last):
        """ See: lbrycrd/src/lbry.cpp """

        if height == 0:
            return self.ledger.genesis_bits, self.ledger.max_target

        if self.ledger.verify_bits_to_target:
            bits = last['bits']
            bitsN = (bits >> 24) & 0xff
            assert 0x03 <= bitsN <= 0x1f, \
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
        return self._value > x
