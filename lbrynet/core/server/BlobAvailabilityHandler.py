import logging
from twisted.internet import defer
from zope.interface import implements
from lbrynet.interfaces import IQueryHandlerFactory, IQueryHandler


class BlobAvailabilityHandlerFactory(object):
    implements(IQueryHandlerFactory)

    def __init__(self, blob_manager):
        self.blob_manager = blob_manager

    ######### IQueryHandlerFactory #########

    def build_query_handler(self):
        q_h = BlobAvailabilityHandler(self.blob_manager)
        return q_h

    def get_primary_query_identifier(self):
        return 'requested_blobs'

    def get_description(self):
        return "Blob Availability - blobs that are available to be uploaded"


class BlobAvailabilityHandler(object):
    implements(IQueryHandler)

    def __init__(self, blob_manager):
        self.blob_manager = blob_manager
        self.query_identifiers = ['requested_blobs']

    ######### IQueryHandler #########

    def register_with_request_handler(self, request_handler, peer):
        request_handler.register_query_handler(self, self.query_identifiers)

    def handle_queries(self, queries):
        if self.query_identifiers[0] in queries:
            logging.debug("Received the client's list of requested blobs")
            d = self._get_available_blobs(queries[self.query_identifiers[0]])

            def set_field(available_blobs):
                return {'available_blobs': available_blobs}

            d.addCallback(set_field)
            return d
        return defer.succeed({})

    ######### internal #########

    def _get_available_blobs(self, requested_blobs):
        d = self.blob_manager.completed_blobs(requested_blobs)

        return d