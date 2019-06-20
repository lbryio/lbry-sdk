from torba.client.basenetwork import BaseNetwork


class Network(BaseNetwork):

    def get_server_height(self):
        return self.rpc('blockchain.block.get_server_height', [])

    def get_claims_by_ids(self, claim_ids):
        return self.rpc('blockchain.claimtrie.getclaimsbyids', claim_ids)

    def resolve(self, urls):
        return self.rpc('blockchain.claimtrie.resolve', urls)

    def claim_search(self, **kwargs):
        return self.rpc('blockchain.claimtrie.search', kwargs)
