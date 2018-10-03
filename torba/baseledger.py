import os
import logging
from binascii import hexlify, unhexlify
from typing import Dict, Type, Iterable
from operator import itemgetter
from collections import namedtuple

from twisted.internet import defer

from torba import baseaccount
from torba import basenetwork
from torba import basetransaction
from torba.basedatabase import BaseDatabase
from torba.baseheader import BaseHeaders
from torba.coinselection import CoinSelector
from torba.constants import COIN, NULL_HASH32
from torba.stream import StreamController
from torba.hash import hash160, double_sha256, sha256, Base58

log = logging.getLogger(__name__)

LedgerType = Type['BaseLedger']


class LedgerRegistry(type):

    ledgers: Dict[str, LedgerType] = {}

    def __new__(mcs, name, bases, attrs):
        cls: LedgerType = super().__new__(mcs, name, bases, attrs)
        if not (name == 'BaseLedger' and not bases):
            ledger_id = cls.get_id()
            assert ledger_id not in mcs.ledgers,\
                'Ledger with id "{}" already registered.'.format(ledger_id)
            mcs.ledgers[ledger_id] = cls
        return cls

    @classmethod
    def get_ledger_class(mcs, ledger_id: str) -> LedgerType:
        return mcs.ledgers[ledger_id]


class TransactionEvent(namedtuple('TransactionEvent', ('address', 'tx'))):
    pass


class BlockHeightEvent(namedtuple('BlockHeightEvent', ('height', 'change'))):
    pass


class BaseLedger(metaclass=LedgerRegistry):

    name: str
    symbol: str
    network_name: str

    database_class = BaseDatabase
    account_class = baseaccount.BaseAccount
    network_class = basenetwork.BaseNetwork
    transaction_class = basetransaction.BaseTransaction

    headers_class: Type[BaseHeaders]

    pubkey_address_prefix: bytes
    script_address_prefix: bytes
    extended_public_key_prefix: bytes
    extended_private_key_prefix: bytes

    default_fee_per_byte = 10

    def __init__(self, config=None):
        self.config = config or {}
        self.db: BaseDatabase = self.config.get('db') or self.database_class(
            os.path.join(self.path, "blockchain.db")
        )
        self.db.ledger = self
        self.headers: BaseHeaders = self.config.get('headers') or self.headers_class(
            os.path.join(self.path, "headers")
        )
        self.network = self.config.get('network') or self.network_class(self)
        self.network.on_header.listen(self.receive_header)
        self.network.on_status.listen(self.receive_status)
        self.accounts = []
        self.fee_per_byte: int = self.config.get('fee_per_byte', self.default_fee_per_byte)

        self._on_transaction_controller = StreamController()
        self.on_transaction = self._on_transaction_controller.stream
        self.on_transaction.listen(
            lambda e: log.info(
                '(%s) on_transaction: address=%s, height=%s, is_verified=%s, tx.id=%s',
                self.get_id(), e.address, e.tx.height, e.tx.is_verified, e.tx.id
            )
        )

        self._on_header_controller = StreamController()
        self.on_header = self._on_header_controller.stream
        self.on_header.listen(
            lambda change: log.info(
                '%s: added %s header blocks, final height %s',
                self.get_id(), change, self.headers.height
            )
        )

        self._transaction_processing_locks = {}
        self._utxo_reservation_lock = defer.DeferredLock()
        self._header_processing_lock = defer.DeferredLock()

    @classmethod
    def get_id(cls):
        return '{}_{}'.format(cls.symbol.lower(), cls.network_name.lower())

    @classmethod
    def hash160_to_address(cls, h160):
        raw_address = cls.pubkey_address_prefix + h160
        return Base58.encode(bytearray(raw_address + double_sha256(raw_address)[0:4]))

    @staticmethod
    def address_to_hash160(address):
        return Base58.decode(address)[1:21]

    @classmethod
    def public_key_to_address(cls, public_key):
        return cls.hash160_to_address(hash160(public_key))

    @staticmethod
    def private_key_to_wif(private_key):
        return b'\x1c' + private_key + b'\x01'

    @property
    def path(self):
        return os.path.join(self.config['data_path'], self.get_id())

    def add_account(self, account: baseaccount.BaseAccount):
        self.accounts.append(account)

    @defer.inlineCallbacks
    def get_transaction(self, txhash):
        raw, _, _, _ = yield self.db.get_transaction(txhash)
        if raw is not None:
            return self.transaction_class(raw)

    @defer.inlineCallbacks
    def get_private_key_for_address(self, address):
        match = yield self.db.get_address(address)
        if match:
            for account in self.accounts:
                if match['account'] == account.public_key.address:
                    return account.get_private_key(match['chain'], match['position'])

    @defer.inlineCallbacks
    def get_effective_amount_estimators(self, funding_accounts: Iterable[baseaccount.BaseAccount]):
        estimators = []
        for account in funding_accounts:
            utxos = yield account.get_unspent_outputs()
            for utxo in utxos:
                estimators.append(utxo.get_estimator(self))
        return estimators

    @defer.inlineCallbacks
    def get_spendable_utxos(self, amount: int, funding_accounts):
        yield self._utxo_reservation_lock.acquire()
        try:
            txos = yield self.get_effective_amount_estimators(funding_accounts)
            selector = CoinSelector(
                txos, amount,
                self.transaction_class.output_class.pay_pubkey_hash(COIN, NULL_HASH32).get_fee(self)
            )
            spendables = selector.select()
            if spendables:
                yield self.reserve_outputs(s.txo for s in spendables)
        except Exception:
            log.exception('Failed to get spendable utxos:')
            raise
        finally:
            self._utxo_reservation_lock.release()
        return spendables

    def reserve_outputs(self, txos):
        return self.db.reserve_outputs(txos)

    def release_outputs(self, txos):
        return self.db.release_outputs(txos)

    @defer.inlineCallbacks
    def get_local_status(self, address):
        address_details = yield self.db.get_address(address)
        history = address_details['history'] or ''
        h = sha256(history.encode())
        return hexlify(h)

    @defer.inlineCallbacks
    def get_local_history(self, address):
        address_details = yield self.db.get_address(address)
        history = address_details['history'] or ''
        parts = history.split(':')[:-1]
        return list(zip(parts[0::2], map(int, parts[1::2])))

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
    def validate_transaction_and_set_position(self, tx, height):
        if not height <= len(self.headers):
            return False
        merkle = yield self.network.get_merkle(tx.id, height)
        merkle_root = self.get_root_of_merkle_tree(merkle['merkle'], merkle['pos'], tx.hash)
        header = self.headers[height]
        tx.position = merkle['pos']
        tx.is_verified = merkle_root == header['merkle_root']

    @defer.inlineCallbacks
    def start(self):
        if not os.path.exists(self.path):
            os.mkdir(self.path)
        yield defer.gatherResults([
            self.db.open(),
            self.headers.open()
        ])
        first_connection = self.network.on_connected.first
        self.network.start()
        yield first_connection
        yield self.update_headers()
        yield self.network.subscribe_headers()
        yield self.update_accounts()

    @defer.inlineCallbacks
    def stop(self):
        yield self.network.stop()
        yield self.db.close()
        yield self.headers.close()

    @defer.inlineCallbacks
    def update_headers(self, height=None, headers=None, subscription_update=False):
        rewound = 0
        while True:

            if height is None or height > len(self.headers):
                # sometimes header subscription updates are for a header in the future
                # which can't be connected, so we do a normal header sync instead
                height = len(self.headers)
                headers = None
                subscription_update = False

            if not headers:
                header_response = yield self.network.get_headers(height, 2001)
                headers = header_response['hex']

            if not headers:
                # Nothing to do, network thinks we're already at the latest height.
                return

            added = yield self.headers.connect(height, unhexlify(headers))
            if added > 0:
                height += added
                self._on_header_controller.add(
                    BlockHeightEvent(self.headers.height, added))

                if rewound > 0:
                    # we started rewinding blocks and apparently found
                    # a new chain
                    rewound = 0
                    yield self.db.rewind_blockchain(height)

                if subscription_update:
                    # subscription updates are for latest header already
                    # so we don't need to check if there are newer / more
                    # on another loop of update_headers(), just return instead
                    return

            elif added == 0:
                # we had headers to connect but none got connected, probably a reorganization
                height -= 1
                rewound += 1
                log.warning(
                    "Blockchain Reorganization: attempting rewind to height %s from starting height %s",
                    height, height+rewound
                )

            else:
                raise IndexError("headers.connect() returned negative number ({})".format(added))

            if height < 0:
                raise IndexError(
                    "Blockchain reorganization rewound all the way back to genesis hash. "
                    "Something is very wrong. Maybe you are on the wrong blockchain?"
                )

            if rewound >= 100:
                raise IndexError(
                    "Blockchain reorganization dropped {} headers. This is highly unusual. "
                    "Will not continue to attempt reorganizing. Please, delete the ledger "
                    "synchronization directory inside your wallet directory (folder: '{}') and "
                    "restart the program to synchronize from scratch."
                    .format(rewound, self.get_id())
                )

            headers = None  # ready to download some more headers

            # if we made it this far and this was a subscription_update
            # it means something went wrong and now we're doing a more
            # robust sync, turn off subscription update shortcut
            subscription_update = False

    @defer.inlineCallbacks
    def receive_header(self, response):
        yield self._header_processing_lock.acquire()
        try:
            header = response[0]
            yield self.update_headers(
                height=header['height'], headers=header['hex'], subscription_update=True
            )
        finally:
            self._header_processing_lock.release()

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
        addresses = yield account.get_addresses(max_used_times=0)
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

            if i < len(local_history) and local_history[i] == (hex_id, remote_height):
                continue

            lock = self._transaction_processing_locks.setdefault(hex_id, defer.DeferredLock())

            yield lock.acquire()

            try:

                # see if we have a local copy of transaction, otherwise fetch it from server
                tx = yield self.db.get_transaction(hex_id)
                save_tx = None
                if tx is None:
                    _raw = yield self.network.get_transaction(hex_id)
                    tx = self.transaction_class(unhexlify(_raw))
                    save_tx = 'insert'

                tx.height = remote_height

                if remote_height > 0 and (not tx.is_verified or tx.position == -1):
                    yield self.validate_transaction_and_set_position(tx, remote_height)
                    if save_tx is None:
                        save_tx = 'update'

                yield self.db.save_transaction_io(
                    save_tx, tx, address, self.address_to_hash160(address),
                    ''.join('{}:{}:'.format(tx_id, tx_height) for tx_id, tx_height in synced_history)
                )

                log.debug(
                    "%s: sync'ed tx %s for address: %s, height: %s, verified: %s",
                    self.get_id(), hex_id, address, tx.height, tx.is_verified
                )

                self._on_transaction_controller.add(TransactionEvent(address, tx))

            except Exception:
                log.exception('Failed to synchronize transaction:')
                raise

            finally:
                lock.release()
                if not lock.locked and hex_id in self._transaction_processing_locks:
                    del self._transaction_processing_locks[hex_id]

    @defer.inlineCallbacks
    def subscribe_history(self, address):
        remote_status = yield self.network.subscribe_address(address)
        local_status = yield self.get_local_status(address)
        if local_status != remote_status:
            yield self.update_history(address)

    @defer.inlineCallbacks
    def receive_status(self, response):
        address, remote_status = response
        local_status = yield self.get_local_status(address)
        if local_status != remote_status:
            yield self.update_history(address)

    def broadcast(self, tx):
        return self.network.broadcast(hexlify(tx.raw).decode())
