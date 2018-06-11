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
        self.db = self.database_class(
            db or os.path.join(self.path, "blockchain.db")
        )  # type: basedatabase.BaseSQLiteWalletStorage
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

    def account_created(self, account):
        self.accounts.add(account)

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
        return os.path.join(self.config['path'], self.get_id())

    def get_input_output_fee(self, io):
        """ Fee based on size of the input / output. """
        return self.fee_per_byte * io.size

    def get_transaction_base_fee(self, tx):
        """ Fee for the transaction header and all outputs; without inputs. """
        return self.fee_per_byte * tx.base_size

    def get_keys(self, account, chain):
        return self.db.get_keys(account, chain)

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

    @defer.inlineCallbacks
    def get_private_key_for_address(self, address):
        match = yield self.db.get_address_details(address)
        if match:
            for account in self.accounts:
                if bytes(match['account']) == account.public_key.address:
                    defer.returnValue(account.get_private_key(match['chain'], match['position']))

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
        addresses = yield account.get_unused_addresses(account)
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
        hashes = list(map(itemgetter('tx_hash'), history))
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
