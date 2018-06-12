from torba.basenetwork import BaseNetwork


class Network(BaseNetwork):

    def get_values_for_uris(self, uris):
        return self.rpc('blockchain.claimtrie.getvaluesforuris', uris)
