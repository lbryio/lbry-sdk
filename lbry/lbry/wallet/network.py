from torba.client.basenetwork import BaseNetwork


class Network(BaseNetwork):

    def get_claims_by_ids(self, claim_ids):
        return self.rpc('blockchain.claimtrie.getclaimsbyids', claim_ids)

    def resolve(self, urls):
        return self.rpc('blockchain.claimtrie.resolve', urls)

    def get_name_proofs(self, block_hash, *names):
        return self.rpc('blockchain.claimtrie.getnameproofs', (block_hash, *names))

    def claim_search(self, **kwargs):
        return self.rpc('blockchain.claimtrie.search', kwargs)
