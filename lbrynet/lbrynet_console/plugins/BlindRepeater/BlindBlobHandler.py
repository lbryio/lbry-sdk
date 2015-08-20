from zope.interface import implements
from lbrynet.interfaces import IBlobHandler
from twisted.internet import defer


class BlindBlobHandler(object):
    implements(IBlobHandler)

    def __init__(self):
        pass

    ######### IBlobHandler #########

    def handle_blob(self, blob, blob_info):
        return defer.succeed(True)