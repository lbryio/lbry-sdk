import os
import logging

from twisted.internet import defer

import lbryschema

from .protocol import Network
from .blockchain import BlockchainHeaders
from .wallet import Wallet

log = logging.getLogger(__name__)


def chunks(l, n):
    for i in range(0, len(l), n):
        yield l[i:i+n]


class WalletManager:

    def __init__(self, storage, config):
        self.storage = storage
        self.config = config
        lbryschema.BLOCKCHAIN_NAME = config['chain']
        self.headers = BlockchainHeaders(self.headers_path, config['chain'])
        self.wallet = Wallet(self.wallet_path)
        self.network = Network(config)
        self.network.on_header.listen(self.process_header)
        self.network.on_transaction.listen(self.process_transaction)
        self._downloading_headers = False

    @property
    def headers_path(self):
        filename = 'blockchain_headers'
        if self.config['chain'] != 'lbrycrd_main':
            filename = '{}_headers'.format(self.config['chain'].split("_")[1])
        return os.path.join(self.config['wallet_path'], filename)

    @property
    def wallet_path(self):
        return os.path.join(self.config['wallet_path'], 'wallets', 'default_wallet')

    @defer.inlineCallbacks
    def start(self):
        self.wallet.load()
        self.network.start()
        yield self.network.on_connected.first
        yield self.download_headers()
        yield self.network.headers_subscribe()
        yield self.download_transactions()

    def stop(self):
        return self.network.stop()

    @defer.inlineCallbacks
    def download_headers(self):
        self._downloading_headers = True
        while True:
            sought_height = len(self.headers)
            headers = yield self.network.block_headers(sought_height)
            log.info("received {} headers starting at {} height".format(headers['count'], sought_height))
            if headers['count'] <= 0:
                break
            yield self.headers.connect(sought_height, headers['hex'].decode('hex'))
        self._downloading_headers = False

    @defer.inlineCallbacks
    def process_header(self, header):
        if self._downloading_headers:
            return
        if header['block_height'] == len(self.headers):
            # New header from network directly connects after the last local header.
            yield self.headers.connect(len(self.headers), header['hex'].decode('hex'))
        elif header['block_height'] > len(self.headers):
            # New header is several heights ahead of local, do download instead.
            yield self.download_headers()

    @defer.inlineCallbacks
    def download_transactions(self):
        for addresses in chunks(self.wallet.addresses, 500):
            self.network.rpc([
                ('blockchain.address.subscribe', [address])
                for address in addresses
            ])

    def process_transaction(self, tx):
        pass
