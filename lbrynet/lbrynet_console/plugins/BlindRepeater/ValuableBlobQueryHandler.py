from lbrynet.interfaces import IQueryHandlerFactory, IQueryHandler
from zope.interface import implements
from twisted.internet import defer
import logging


class ValuableQueryHandler(object):
    implements(IQueryHandler)

    def __init__(self, wallet, payment_rate_manager):
        self.wallet = wallet
        self.payment_rate_manager = payment_rate_manager
        self.peer = None
        self.payment_rate = None
        self.query_identifiers = []

    ######### IQueryHandler #########

    def register_with_request_handler(self, request_handler, peer):
        self.peer = peer
        request_handler.register_query_handler(self, self.query_identifiers)

    def handle_queries(self, queries):
        pass


class ValuableBlobHashQueryHandlerFactory(object):
    implements(IQueryHandlerFactory)

    def __init__(self, peer_finder, wallet, payment_rate_manager):
        self.peer_finder = peer_finder
        self.wallet = wallet
        self.payment_rate_manager = payment_rate_manager

    ######### IQueryHandlerFactory #########

    def build_query_handler(self):
        q_h = ValuableBlobHashQueryHandler(self.wallet, self.payment_rate_manager, self.peer_finder)
        return q_h

    def get_primary_query_identifier(self):
        return 'valuable_blob_hashes'

    def get_description(self):
        return "Valuable Hashes - Hashes of blobs that it may be valuable to repeat"


class ValuableBlobHashQueryHandler(ValuableQueryHandler):
    implements(IQueryHandler)

    def __init__(self, wallet, payment_rate_manager, peer_finder):
        ValuableQueryHandler.__init__(self, wallet, payment_rate_manager)
        self.peer_finder = peer_finder
        self.query_identifiers = ['valuable_blob_hashes', 'valuable_blob_payment_rate']
        self.valuable_blob_hash_payment_rate = None
        self.blob_length_payment_rate = None

    ######### IQueryHandler #########

    def handle_queries(self, queries):
        response = {}

        def set_fields(fields):
            response.update(fields)

        if self.query_identifiers[1] in queries:
            d = self._handle_valuable_blob_payment_rate(queries[self.query_identifiers[1]])
            d.addCallback(set_fields)
        else:
            d = defer.succeed(True)

        if self.query_identifiers[0] in queries:
            d.addCallback(lambda _: self._handle_valuable_blob_hashes(queries[self.query_identifiers[0]]))
            d.addCallback(set_fields)

        d.addCallback(lambda _: response)
        return d

    ######### internal #########

    def _handle_valuable_blob_payment_rate(self, requested_payment_rate):
        if not self.payment_rate_manager.accept_rate_valuable_blob_hash(self.peer, "VALUABLE_BLOB_HASH",
                                                                        requested_payment_rate):
            r = "RATE_TOO_LOW"
        else:
            self.valuable_blob_hash_payment_rate = requested_payment_rate
            r = "RATE_ACCEPTED"
        return defer.succeed({'valuable_blob_payment_rate': r})

    def _handle_valuable_blob_hashes(self, request):
        # TODO: eventually, look at the request and respond appropriately given the 'reference' field
        if self.valuable_blob_hash_payment_rate is not None:
            max_hashes = 20
            if 'max_blob_hashes' in request:
                max_hashes = int(request['max_blob_hash'])
            valuable_hashes = self.peer_finder.get_most_popular_blobs(max_hashes)
            hashes_and_scores = []
            for blob_hash, count in valuable_hashes:
                hashes_and_scores.append((blob_hash, 1.0 * count / 10.0))
            if len(hashes_and_scores) != 0:
                logging.info("Responding to a valuable blob hashes request with %s blob hashes: %s",
                             str(len(hashes_and_scores)))
                expected_payment = 1.0 * len(hashes_and_scores) * self.valuable_blob_hash_payment_rate / 1000.0
                self.wallet.add_expected_payment(self.peer, expected_payment)
                self.peer.update_stats('uploaded_valuable_blob_hashes', len(hashes_and_scores))
            return defer.succeed({'valuable_blob_hashes': {'blob_hashes': hashes_and_scores}})
        return defer.succeed({'valuable_blob_hashes': {'error': "RATE_UNSET"}})


class ValuableBlobLengthQueryHandlerFactory(object):
    implements(IQueryHandlerFactory)

    def __init__(self, wallet, payment_rate_manager, blob_manager):
        self.blob_manager = blob_manager
        self.wallet = wallet
        self.payment_rate_manager = payment_rate_manager

    ######### IQueryHandlerFactory #########

    def build_query_handler(self):
        q_h = ValuableBlobLengthQueryHandler(self.wallet, self.payment_rate_manager, self.blob_manager)
        return q_h

    def get_primary_query_identifier(self):
        return 'blob_length'

    def get_description(self):
        return "Valuable Blob Lengths - Lengths of blobs that it may be valuable to repeat"


class ValuableBlobLengthQueryHandler(ValuableQueryHandler):

    def __init__(self, wallet, payment_rate_manager, blob_manager):
        ValuableQueryHandler.__init__(self, wallet, payment_rate_manager)
        self.blob_manager = blob_manager
        self.query_identifiers = ['blob_length', 'blob_length_payment_rate']
        self.valuable_blob_hash_payment_rate = None
        self.blob_length_payment_rate = None

    ######## IQueryHandler #########

    def handle_queries(self, queries):
        response = {}

        def set_fields(fields):
            response.update(fields)

        if self.query_identifiers[1] in queries:
            d = self._handle_blob_length_payment_rate(queries[self.query_identifiers[1]])
            d.addCallback(set_fields)
        else:
            d = defer.succeed(True)

        if self.query_identifiers[0] in queries:
            d.addCallback(lambda _: self._handle_blob_length(queries[self.query_identifiers[0]]))
            d.addCallback(set_fields)

        d.addCallback(lambda _: response)
        return d

    ######### internal #########

    def _handle_blob_length_payment_rate(self, requested_payment_rate):
        if not self.payment_rate_manager.accept_rate_valuable_blob_info(self.peer, "VALUABLE_BLOB_INFO",
                                                                        requested_payment_rate):
            r = "RATE_TOO_LOW"
        else:
            self.blob_length_payment_rate = requested_payment_rate
            r = "RATE_ACCEPTED"
        return defer.succeed({'blob_length_payment_rate': r})

    def _handle_blob_length(self, request):
        if self.blob_length_payment_rate is not None:
            assert 'blob_hashes' in request
            ds = []

            def make_response_pair(length, blob_hash):
                return blob_hash, length

            for blob_hash in request['blob_hashes']:
                d = self.blob_manager.get_blob_length(blob_hash)
                d.addCallback(make_response_pair, blob_hash)
                ds.append(d)

            dl = defer.DeferredList(ds)

            def make_response(response_pairs):
                lengths = []
                for success, response_pair in response_pairs:
                    if success is True:
                        lengths.append(response_pair)
                if len(lengths) > 0:
                    logging.info("Responding with %s blob lengths: %s", str(len(lengths)))
                    expected_payment = 1.0 * len(lengths) * self.blob_length_payment_rate / 1000.0
                    self.wallet.add_expected_payment(self.peer, expected_payment)
                    self.peer.update_stats('uploaded_valuable_blob_infos', len(lengths))
                return {'blob_length': {'blob_lengths': lengths}}

            dl.addCallback(make_response)