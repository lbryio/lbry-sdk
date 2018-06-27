import os
import six
import hashlib
import logging
from binascii import hexlify, unhexlify
from typing import Dict, Type, Iterable, Generator
from operator import itemgetter
from collections import namedtuple

from twisted.internet import defer

from torba import baseaccount
from torba import basedatabase
from torba import baseheader
from torba import basenetwork
from torba import basetransaction
from torba.stream import StreamController, execute_serially
from torba.hash import hash160, double_sha256, Base58

log = logging.getLogger(__name__)


class LedgerRegistry(type):
    ledgers = {}  # type: Dict[str, Type[BaseLedger]]

    def __new__(mcs, name, bases, attrs):
        cls = super(LedgerRegistry, mcs).__new__(mcs, name, bases, attrs)  # type: Type[BaseLedger]
        if not (name == 'BaseLedger' and not bases):
            ledger_id = cls.get_id()
            assert ledger_id not in mcs.ledgers,\
                'Ledger with id "{}" already registered.'.format(ledger_id)
            mcs.ledgers[ledger_id] = cls
        return cls

    @classmethod
    def get_ledger_class(mcs, ledger_id):  # type: (str) -> Type[BaseLedger]
        return mcs.ledgers[ledger_id]


class TransactionEvent(namedtuple('TransactionEvent', ('address', 'tx', 'height', 'is_verified'))):
    pass


class BaseLedger(six.with_metaclass(LedgerRegistry)):

    name = None
    symbol = None
    network_name = None

    account_class = baseaccount.BaseAccount
    database_class = basedatabase.BaseDatabase
    headers_class = baseheader.BaseHeaders
    network_class = basenetwork.BaseNetwork
    transaction_class = basetransaction.BaseTransaction

    secret_prefix = None
    pubkey_address_prefix = None
    script_address_prefix = None
    extended_public_key_prefix = None
    extended_private_key_prefix = None

    default_fee_per_byte = 10

    def __init__(self, config=None, db=None, network=None, headers_class=None):
        self.config = config or {}
        self.db = db or self.database_class(
            os.path.join(self.path, "blockchain.db")
        )  # type: basedatabase.BaseDatabase
        self.network = network or self.network_class(self)
        self.network.on_header.listen(self.process_header)
        self.network.on_status.listen(self.process_status)
        self.accounts = set()
        self.headers = (headers_class or self.headers_class)(self)
        self.fee_per_byte = self.config.get('fee_per_byte', self.default_fee_per_byte)

        self._on_transaction_controller = StreamController()
        self.on_transaction = self._on_transaction_controller.stream
        self.on_transaction.listen(
            lambda e: log.info('({}) on_transaction: address={}, height={}, is_verified={}, tx.id={}'.format(
                self.get_id(), e.address, e.height, e.is_verified, e.tx.hex_id)
            )
        )

        self._on_header_controller = StreamController()
        self.on_header = self._on_header_controller.stream

        self._transaction_processing_locks = {}

    @classmethod
    def get_id(cls):
        return '{}_{}'.format(cls.symbol.lower(), cls.network_name.lower())

    def hash160_to_address(self, h160):
        raw_address = self.pubkey_address_prefix + h160
        return Base58.encode(bytearray(raw_address + double_sha256(raw_address)[0:4]))

    @staticmethod
    def address_to_hash160(address):
        bytes = Base58.decode(address)
        prefix, pubkey_bytes, addr_checksum = bytes[0], bytes[1:21], bytes[21:]
        return pubkey_bytes

    def public_key_to_address(self, public_key):
        return self.hash160_to_address(hash160(public_key))

    @staticmethod
    def private_key_to_wif(private_key):
        return b'\x1c' + private_key + b'\x01'

    @property
    def path(self):
        return os.path.join(self.config['wallet_path'], self.get_id())

    def get_input_output_fee(self, io):
        """ Fee based on size of the input / output. """
        return self.fee_per_byte * io.size

    def get_transaction_base_fee(self, tx):
        """ Fee for the transaction header and all outputs; without inputs. """
        return self.fee_per_byte * tx.base_size

    @defer.inlineCallbacks
    def add_account(self, account):  # type: (baseaccount.BaseAccount) -> None
        self.accounts.add(account)
        if self.network.is_connected:
            yield self.update_account(account)

    @defer.inlineCallbacks
    def get_private_key_for_address(self, address):
        match = yield self.db.get_address(address)
        if match:
            for account in self.accounts:
                if bytes(match['account']) == account.public_key.address:
                    defer.returnValue(account.get_private_key(match['chain'], match['position']))

    def get_unspent_outputs(self, account):
        return self.db.get_utxos(account, self.transaction_class.output_class)

    @defer.inlineCallbacks
    def get_effective_amount_estimators(self, funding_accounts):
        # type: (Iterable[baseaccount.BaseAccount]) -> defer.Deferred
        estimators = []
        for account in funding_accounts:
            utxos = yield self.get_unspent_outputs(account)
            for utxo in utxos:
                estimators.append(utxo.get_estimator(self))
        defer.returnValue(estimators)

    @defer.inlineCallbacks
    def get_local_status(self, address):
        address_details = yield self.db.get_address(address)
        history = address_details['history'] or ''
        hash = hashlib.sha256(history.encode()).digest()
        defer.returnValue(hexlify(hash))

    @defer.inlineCallbacks
    def get_local_history(self, address):
        address_details = yield self.db.get_address(address)
        history = address_details['history'] or ''
        parts = history.split(':')[:-1]
        defer.returnValue(list(zip(parts[0::2], map(int, parts[1::2]))))

    @staticmethod
    def get_root_of_merkle_tree(branches, branch_positions, working_branch):
        for i, branch in enumerate(branches):
            other_branch = unhexlify(branch)[::-1]
            other_branch_on_left = bool((branch_positions >> i) & 1)
            if other_branch_on_left:
                combined = other_branch + working_branch
            else:
                combined = working_branch + other_branch
            working_branch = double_sha256(combined)
        return hexlify(working_branch[::-1])

    @defer.inlineCallbacks
    def is_valid_transaction(self, tx, height):
        height <= len(self.headers) or defer.returnValue(False)
        merkle = yield self.network.get_merkle(tx.hex_id.decode(), height)
        merkle_root = self.get_root_of_merkle_tree(merkle['merkle'], merkle['pos'], tx.hash)
        header = self.headers[height]
        defer.returnValue(merkle_root == header['merkle_root'])

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

    @defer.inlineCallbacks
    def stop(self):
        yield self.network.stop()
        yield self.db.stop()

    @execute_serially
    @defer.inlineCallbacks
    def update_headers(self):
        while True:
            height_sought = len(self.headers)
            headers = yield self.network.get_headers(height_sought)
            if headers['count'] <= 0:
                break
            yield self.headers.connect(height_sought, unhexlify(headers['hex']))
            self._on_header_controller.add(height_sought)

    @defer.inlineCallbacks
    def process_header(self, response):
        header = response[0]
        if self.update_headers.is_running:
            return
        if header['height'] == len(self.headers):
            # New header from network directly connects after the last local header.
            yield self.headers.connect(len(self.headers), unhexlify(header['hex']))
            self._on_header_controller.add(len(self.headers))
        elif header['height'] > len(self.headers):
            # New header is several heights ahead of local, do download instead.
            yield self.update_headers()

    @execute_serially
    def update_accounts(self):
        return defer.DeferredList([
            self.update_account(a) for a in self.accounts
        ])

    @defer.inlineCallbacks
    def update_account(self, account):  # type: (baseaccount.BaseAccount) -> defer.Defferred
        # Before subscribing, download history for any addresses that don't have any,
        # this avoids situation where we're getting status updates to addresses we know
        # need to update anyways. Continue to get history and create more addresses until
        # all missing addresses are created and history for them is fully restored.
        yield account.ensure_address_gap()
        addresses = yield account.get_unused_addresses()
        while addresses:
            yield defer.DeferredList([
                self.update_history(a) for a in addresses
            ])
            addresses = yield account.ensure_address_gap()

        # By this point all of the addresses should be restored and we
        # can now subscribe all of them to receive updates.
        all_addresses = yield account.get_addresses()
        yield defer.DeferredList(
            list(map(self.subscribe_history, all_addresses))
        )

    @defer.inlineCallbacks
    def update_history(self, address):
        remote_history = yield self.network.get_history(address)
        local_history = yield self.get_local_history(address)

        synced_history = []
        for i, (hex_id, remote_height) in enumerate(map(itemgetter('tx_hash', 'height'), remote_history)):

            synced_history.append((hex_id, remote_height))

            if i < len(local_history) and local_history[i] == (hex_id.decode(), remote_height):
                continue

            lock = self._transaction_processing_locks.setdefault(hex_id, defer.DeferredLock())

            yield lock.acquire()

            try:
                # see if we have a local copy of transaction, otherwise fetch it from server
                raw, local_height, is_verified = yield self.db.get_transaction(unhexlify(hex_id)[::-1])
                save_tx = None
                if raw is None:
                    _raw = yield self.network.get_transaction(hex_id)
                    tx = self.transaction_class(unhexlify(_raw))
                    save_tx = 'insert'
                else:
                    tx = self.transaction_class(raw)

                if remote_height > 0 and not is_verified:
                    is_verified = yield self.is_valid_transaction(tx, remote_height)
                    is_verified = 1 if is_verified else 0
                    if save_tx is None:
                        save_tx = 'update'

                yield self.db.save_transaction_io(
                    save_tx, tx, remote_height, is_verified, address, self.address_to_hash160(address),
                    ''.join('{}:{}:'.format(tx_id.decode(), tx_height) for tx_id, tx_height in synced_history)
                )

                self._on_transaction_controller.add(TransactionEvent(address, tx, remote_height, is_verified))

            finally:
                lock.release()
                if not lock.locked:
                    del self._transaction_processing_locks[hex_id]

    @defer.inlineCallbacks
    def subscribe_history(self, address):
        remote_status = yield self.network.subscribe_address(address)
        local_status = yield self.get_local_status(address)
        if local_status != remote_status:
            yield self.update_history(address)

    @defer.inlineCallbacks
    def process_status(self, response):
        address, remote_status = response
        local_status = yield self.get_local_status(address)
        if local_status != remote_status:
            yield self.update_history(address)

    def broadcast(self, tx):
        return self.network.broadcast(hexlify(tx.raw))
