from torba.basenetwork import BaseNetwork


class Network(BaseNetwork):

    def get_values_for_uris(self, block_hash, *uris):
        return self.rpc('blockchain.claimtrie.getvaluesforuris', block_hash, *uris)
