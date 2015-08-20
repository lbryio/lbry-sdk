from zope.interface import Interface


class IBlobScorer(Interface):
    def score_blob(self, blob, blob_info):
        pass