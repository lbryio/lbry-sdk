import logging
from binascii import unhexlify
from operator import itemgetter
from twisted.internet import defer

from lbrynet.wallet.wallet import Wallet
from lbrynet.wallet.ledger import Ledger
from lbrynet.wallet.protocol import Network
from lbrynet.wallet.transaction import Transaction
from lbrynet.wallet.stream import execute_serially
from lbrynet.wallet.constants import MAXIMUM_FEE_PER_BYTE, MAXIMUM_FEE_PER_NAME_CHAR

log = logging.getLogger(__name__)


class WalletManager:

    def __init__(self, config=None, wallet=None, ledger=None, network=None):
        self.config = config or {}
        self.ledger = ledger or Ledger(self.config)
        self.wallet = wallet or Wallet()
        self.wallets = [self.wallet]
        self.network = network or Network(self.config)
        self.network.on_header.listen(self.process_header)
        self.network.on_status.listen(self.process_status)

    @property
    def fee_per_byte(self):
        return self.config.get('fee_per_byte', MAXIMUM_FEE_PER_BYTE)

    @property
    def fee_per_name_char(self):
        return self.config.get('fee_per_name_char', MAXIMUM_FEE_PER_NAME_CHAR)

    @property
    def addresses_without_history(self):
        for wallet in self.wallets:
            for address in wallet.addresses:
                if not self.ledger.has_address(address):
                    yield address

    def get_least_used_receiving_address(self, max_transactions=1000):
        return self._get_least_used_address(
            self.wallet.default_account.receiving_keys.addresses,
            self.wallet.default_account.receiving_keys,
            max_transactions
        )

    def get_least_used_change_address(self, max_transactions=100):
        return self._get_least_used_address(
            self.wallet.default_account.change_keys.addresses,
            self.wallet.default_account.change_keys,
            max_transactions
        )

    def _get_least_used_address(self, addresses, sequence, max_transactions):
        address = self.ledger.get_least_used_address(addresses, max_transactions)
        if address:
            return address
        address = sequence.generate_next_address()
        self.subscribe_history(address)
        return address

    @defer.inlineCallbacks
    def start(self):
        first_connection = self.network.on_connected.first
        self.network.start()
        yield first_connection
        self.ledger.headers.touch()
        yield self.update_headers()
        yield self.network.subscribe_headers()
        yield self.update_wallet()

    def stop(self):
        return self.network.stop()

    @execute_serially
    @defer.inlineCallbacks
    def update_headers(self):
        while True:
            height_sought = len(self.ledger.headers)
            headers = yield self.network.get_headers(height_sought)
            log.info("received {} headers starting at {} height".format(headers['count'], height_sought))
            if headers['count'] <= 0:
                break
            yield self.ledger.headers.connect(height_sought, headers['hex'].decode('hex'))

    @defer.inlineCallbacks
    def process_header(self, response):
        header = response[0]
        if self.update_headers.is_running:
            return
        if header['height'] == len(self.ledger.headers):
            # New header from network directly connects after the last local header.
            yield self.ledger.headers.connect(len(self.ledger.headers), header['hex'].decode('hex'))
        elif header['height'] > len(self.ledger.headers):
            # New header is several heights ahead of local, do download instead.
            yield self.update_headers()

    @execute_serially
    @defer.inlineCallbacks
    def update_wallet(self):
        # Before subscribing, download history for any addresses that don't have any,
        # this avoids situation where we're getting status updates to addresses we know
        # need to update anyways. Continue to get history and create more addresses until
        # all missing addresses are created and history for them is fully restored.
        self.wallet.ensure_enough_addresses()
        addresses = list(self.addresses_without_history)
        while addresses:
            yield defer.gatherResults([
                self.update_history(a) for a in addresses
            ])
            addresses = self.wallet.ensure_enough_addresses()

        # By this point all of the addresses should be restored and we
        # can now subscribe all of them to receive updates.
        yield defer.gatherResults([
            self.subscribe_history(address)
            for address in self.wallet.addresses
        ])

    @defer.inlineCallbacks
    def update_history(self, address):
        history = yield self.network.get_history(address)
        for hash in map(itemgetter('tx_hash'), history):
            transaction = self.ledger.get_transaction(hash)
            if not transaction:
                raw = yield self.network.get_transaction(hash)
                transaction = Transaction(unhexlify(raw))
            self.ledger.add_transaction(address, transaction)

    @defer.inlineCallbacks
    def subscribe_history(self, address):
        status = yield self.network.subscribe_address(address)
        if status != self.ledger.get_status(address):
            self.update_history(address)

    def process_status(self, response):
        address, status = response
        if status != self.ledger.get_status(address):
            self.update_history(address)
