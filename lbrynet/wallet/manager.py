import os
import logging
from operator import itemgetter

from twisted.internet import defer

import lbryschema

from .protocol import Network
from .blockchain import BlockchainHeaders, Transaction
from .wallet import Wallet
from .stream import execute_serially

log = logging.getLogger(__name__)


class WalletManager:

    def __init__(self, storage, config):
        self.storage = storage
        self.config = config
        lbryschema.BLOCKCHAIN_NAME = config['chain']
        self.headers = BlockchainHeaders(self.headers_path, config['chain'])
        self.wallet = Wallet(self.wallet_path, self.headers)
        self.network = Network(config)
        self.network.on_header.listen(self.process_header)
        self.network.on_status.listen(self.process_status)

    @property
    def headers_path(self):
        filename = 'blockchain_headers'
        if self.config['chain'] != 'lbrycrd_main':
            filename = '{}_headers'.format(self.config['chain'].split("_")[1])
        return os.path.join(self.config['wallet_path'], filename)

    @property
    def wallet_path(self):
        return os.path.join(self.config['wallet_path'], 'wallets', 'default_wallet')

    def get_least_used_receiving_address(self, max_transactions=1000):
        return self._get_least_used_address(
            self.wallet.receiving_addresses,
            self.wallet.default_account.receiving,
            max_transactions
        )

    def get_least_used_change_address(self, max_transactions=100):
        return self._get_least_used_address(
            self.wallet.change_addresses,
            self.wallet.default_account.change,
            max_transactions
        )

    def _get_least_used_address(self, addresses, sequence, max_transactions):
        transaction_counts = []
        for address in addresses:
            transactions = self.wallet.history.get_transactions(address, [])
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

        address = sequence.generate_next_address()
        self.subscribe_history(address)
        return address

    @defer.inlineCallbacks
    def start(self):
        self.network.start()
        yield self.network.on_connected.first
        yield self.update_headers()
        yield self.network.subscribe_headers()
        yield self.update_wallet()

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
    @defer.inlineCallbacks
    def update_wallet(self):

        if not self.wallet.exists:
            self.wallet.create()

        # Before subscribing, download history for any addresses that don't have any,
        # this avoids situation where we're getting status updates to addresses we know
        # need to update anyways. Continue to get history and create more addresses until
        # all missing addresses are created and history for them is fully restored.
        self.wallet.ensure_enough_addresses()
        addresses = list(self.wallet.addresses_without_history)
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
            transaction = self.wallet.history.get_transaction(hash)
            if not transaction:
                raw = yield self.network.get_transaction(hash)
                transaction = Transaction(hash, raw, None)
            self.wallet.history.add_transaction(address, transaction)

    @defer.inlineCallbacks
    def subscribe_history(self, address):
        status = yield self.network.subscribe_address(address)
        if status != self.wallet.history.get_status(address):
            self.update_history(address)

    def process_status(self, response):
        address, status = response
        if status != self.wallet.history.get_status(address):
            self.update_history(address)
