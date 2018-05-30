import logging
from twisted.internet import defer
from twisted.internet.protocol import ClientFactory
from client import StratumClientProtocol
from errors import TransportException

log = logging.getLogger()


class StratumClient(ClientFactory):
    protocol = StratumClientProtocol

    def __init__(self, connected_d=None):
        self.client = None
        self.connected_d = connected_d or defer.Deferred()

    def buildProtocol(self, addr):
        client = self.protocol()
        client.factory = self
        self.client = client
        self.client._connected.addCallback(lambda _: self.connected_d.callback(self))
        return client

    def _rpc(self, method, params, *args, **kwargs):
        if not self.client:
            raise TransportException("Not connected")

        return self.client.rpc(method, params, *args, **kwargs)

    def blockchain_claimtrie_getvaluesforuris(self, block_hash, *uris):
        return self._rpc('blockchain.claimtrie.getvaluesforuris',
                         [block_hash] + list(uris))

    def blockchain_claimtrie_getvaluesforuri(self, block_hash, uri):
        return self._rpc('blockchain.claimtrie.getvaluesforuri', [block_hash, uri])

    def blockchain_claimtrie_getclaimssignedbynthtoname(self, name, n):
        return self._rpc('blockchain.claimtrie.getclaimssignedbynthtoname', [name, n])

    def blockchain_claimtrie_getclaimssignedbyid(self, certificate_id):
        return self._rpc('blockchain.claimtrie.getclaimssignedbyid', [certificate_id])

    def blockchain_claimtrie_getclaimssignedby(self, name):
        return self._rpc('blockchain.claimtrie.getclaimssignedby', [name])

    def blockchain_claimtrie_getnthclaimforname(self, name, n):
        return self._rpc('blockchain.claimtrie.getnthclaimforname', [name, n])

    def blockchain_claimtrie_getclaimsbyids(self, *claim_ids):
        return self._rpc('blockchain.claimtrie.getclaimsbyids', list(claim_ids))

    def blockchain_claimtrie_getclaimbyid(self, claim_id):
        return self._rpc('blockchain.claimtrie.getclaimbyid', [claim_id])

    def blockchain_claimtrie_get(self):
        return self._rpc('blockchain.claimtrie.get', [])

    def blockchain_block_get_block(self, block_hash):
        return self._rpc('blockchain.block.get_block', [block_hash])

    def blockchain_claimtrie_getclaimsforname(self, name):
        return self._rpc('blockchain.claimtrie.getclaimsforname', [name])

    def blockchain_claimtrie_getclaimsintx(self, txid):
        return self._rpc('blockchain.claimtrie.getclaimsintx', [txid])

    def blockchain_claimtrie_getvalue(self, name, block_hash=None):
        return self._rpc('blockchain.claimtrie.getvalue', [name, block_hash])

    def blockchain_relayfee(self):
        return self._rpc('blockchain.relayfee', [])

    def blockchain_estimatefee(self):
        return self._rpc('blockchain.estimatefee', [])

    def blockchain_transaction_get(self, txid):
        return self._rpc('blockchain.transaction.get', [txid])

    def blockchain_transaction_get_merkle(self, tx_hash, height, cache_only=False):
        return self._rpc('blockchain.transaction.get_merkle', [tx_hash, height, cache_only])

    def blockchain_transaction_broadcast(self, raw_transaction):
        return self._rpc('blockchain.transaction.broadcast', [raw_transaction])

    def blockchain_block_get_chunk(self, index, cache_only=False):
        return self._rpc('blockchain.block.get_chunk', [index, cache_only])

    def blockchain_block_get_header(self, height, cache_only=False):
        return self._rpc('blockchain.block.get_header', [height, cache_only])

    def blockchain_utxo_get_address(self, txid, pos):
        return self._rpc('blockchain.utxo.get_address', [txid, pos])

    def blockchain_address_listunspent(self, address):
        return self._rpc('blockchain.address.listunspent', [address])

    def blockchain_address_get_proof(self, address):
        return self._rpc('blockchain.address.get_proof', [address])

    def blockchain_address_get_balance(self, address):
        return self._rpc('blockchain.address.get_balance', [address])

    def blockchain_address_get_mempool(self, address):
        return self._rpc('blockchain.address.get_mempool', [address])

    def blockchain_address_get_history(self, address):
        return self._rpc('blockchain.address.get_history', [address])

    def blockchain_block_get_server_height(self):
        return self._rpc('blockchain.block.get_server_height', [])
