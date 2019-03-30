from torba.client.basenetwork import BaseNetwork


class Network(BaseNetwork):

    def get_server_height(self):
        return self.rpc('blockchain.block.get_server_height', [])

    def get_values_for_uris(self, block_hash, *uris):
        return self.rpc('blockchain.claimtrie.getvaluesforuris', [block_hash, *uris])

    def get_claims_by_ids(self, *claim_ids):
        return self.rpc('blockchain.claimtrie.getclaimsbyids', claim_ids)

    def get_claims_in_tx(self, txid):
        return self.rpc('blockchain.claimtrie.getclaimsintx', [txid])

    def get_claims_for_name(self, name):
        return self.rpc('blockchain.claimtrie.getclaimsforname', [name])

    def get_transaction_height(self, txid):
        # 1.0 protocol specific workaround. Newer protocol should use get_transaction with verbose True
        return self.rpc('blockchain.transaction.get_height', [txid])

    def claim_search(self, **kwargs):
        return self.rpc('blockchain.claimtrie.search', kwargs)
