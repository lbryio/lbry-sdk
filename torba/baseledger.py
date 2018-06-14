import os
import six
import hashlib
from binascii import hexlify, unhexlify
from typing import Dict, Type
from operator import itemgetter

from twisted.internet import defer

from torba import baseaccount
from torba import basedatabase
from torba import baseheader
from torba import basenetwork
from torba import basetransaction
from torba.stream import StreamController, execute_serially
from torba.hash import hash160, double_sha256, Base58


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

    def __init__(self, config=None, db=None, network=None):
        self.config = config or {}
        self.db = db or self.database_class(
            os.path.join(self.path, "blockchain.db")
        )  # type: basedatabase.BaseDatabase
        self.network = network or self.network_class(self)
        self.network.on_header.listen(self.process_header)
        self.network.on_status.listen(self.process_status)
        self.accounts = set()
        self.headers = self.headers_class(self)
        self.fee_per_byte = self.config.get('fee_per_byte', self.default_fee_per_byte)

        self._on_transaction_controller = StreamController()
        self.on_transaction = self._on_transaction_controller.stream

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
    def add_transaction(self, address, transaction, height):
        # type: (bytes, basetransaction.BaseTransaction, int) -> None
        yield self.db.add_transaction(
            address, self.address_to_hash160(address), transaction, height, False
        )
        self._on_transaction_controller.add(transaction)

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
    def get_local_status(self, address):
        address_details = yield self.db.get_address(address)
        hash = hashlib.sha256(address_details['history']).digest()
        defer.returnValue(hexlify(hash))

    @defer.inlineCallbacks
    def get_local_history(self, address):
        address_details = yield self.db.get_address(address)
        history = address_details['history'] or b''
        if six.PY2:
            history = str(history)
        parts = history.split(b':')[:-1]
        defer.returnValue(list(zip(parts[0::2], map(int, parts[1::2]))))

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
        local = yield self.get_local_history(address)

        history_parts = []
        for i, (hash, height) in enumerate(map(itemgetter('tx_hash', 'height'), remote_history)):
            history_parts.append('{}:{}:'.format(hash.decode(), height))
            if i < len(local) and local[i] == (hash, height):
                continue
            raw = yield self.network.get_transaction(hash)
            transaction = self.transaction_class(unhexlify(raw))
            yield self.add_transaction(address, transaction, height)

        yield self.db.set_address_history(
            address, ''.join(history_parts).encode()
        )

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
