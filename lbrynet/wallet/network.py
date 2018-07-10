from torba.basenetwork import BaseNetwork


class Network(BaseNetwork):

    def get_values_for_uris(self, block_hash, *uris):
        return self.rpc('blockchain.claimtrie.getvaluesforuris', block_hash, *uris)

    def get_claims_by_ids(self, *claim_ids):
        return self.rpc("blockchain.claimtrie.getclaimsbyids", *claim_ids)
