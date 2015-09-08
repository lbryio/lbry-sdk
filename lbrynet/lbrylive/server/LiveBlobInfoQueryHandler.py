import logging
from twisted.internet import defer
from zope.interface import implements
from lbrynet.interfaces import IQueryHandlerFactory, IQueryHandler


log = logging.getLogger(__name__)


class CryptBlobInfoQueryHandlerFactory(object):
    implements(IQueryHandlerFactory)

    def __init__(self, stream_info_manager, wallet, payment_rate_manager):
        self.stream_info_manager = stream_info_manager
        self.wallet = wallet
        self.payment_rate_manager = payment_rate_manager

    ######### IQueryHandlerFactory #########

    def build_query_handler(self):
        q_h = CryptBlobInfoQueryHandler(self.stream_info_manager, self.wallet, self.payment_rate_manager)
        return q_h

    def get_primary_query_identifier(self):
        return 'further_blobs'

    def get_description(self):
        return ("Stream Blob Information - blob hashes that are associated with streams,"
                " and the blobs' associated metadata")


class CryptBlobInfoQueryHandler(object):
    implements(IQueryHandler)

    def __init__(self, stream_info_manager, wallet, payment_rate_manager):
        self.stream_info_manager = stream_info_manager
        self.wallet = wallet
        self.payment_rate_manager = payment_rate_manager
        self.query_identifiers = ['blob_info_payment_rate', 'further_blobs']
        self.blob_info_payment_rate = None
        self.peer = None

    ######### IQueryHandler #########

    def register_with_request_handler(self, request_handler, peer):
        self.peer = peer
        request_handler.register_query_handler(self, self.query_identifiers)

    def handle_queries(self, queries):
        response = {}

        if self.query_identifiers[0] in queries:
            if not self.handle_blob_info_payment_rate(queries[self.query_identifiers[0]]):
                return defer.succeed({'blob_info_payment_rate': 'RATE_TOO_LOW'})
            else:
                response['blob_info_payment_rate'] = "RATE_ACCEPTED"

        if self.query_identifiers[1] in queries:
            further_blobs_request = queries[self.query_identifiers[1]]
            log.debug("Received the client's request for additional blob information")

            if self.blob_info_payment_rate is None:
                response['further_blobs'] = {'error': 'RATE_UNSET'}
                return defer.succeed(response)

            def count_and_charge(blob_infos):
                if len(blob_infos) != 0:
                    log.info("Responding with %s infos", str(len(blob_infos)))
                    expected_payment = 1.0 * len(blob_infos) * self.blob_info_payment_rate / 1000.0
                    self.wallet.add_expected_payment(self.peer, expected_payment)
                    self.peer.update_stats('uploaded_crypt_blob_infos', len(blob_infos))
                return blob_infos

            def set_field(further_blobs):
                response['further_blobs'] = {'blob_infos': further_blobs}
                return response

            def get_further_blobs(stream_hash):
                if stream_hash is None:
                    response['further_blobs'] = {'error': 'REFERENCE_HASH_UNKNOWN'}
                    return defer.succeed(response)
                start = further_blobs_request.get("start")
                end = further_blobs_request.get("end")
                count = further_blobs_request.get("count")
                if count is not None:
                    try:
                        count = int(count)
                    except ValueError:
                        response['further_blobs'] = {'error': 'COUNT_NON_INTEGER'}
                        return defer.succeed(response)

                if len([x for x in [start, end, count] if x is not None]) < 2:
                    response['further_blobs'] = {'error': 'TOO_FEW_PARAMETERS'}
                    return defer.succeed(response)

                inner_d = self.get_further_blobs(stream_hash, start, end, count)

                inner_d.addCallback(count_and_charge)
                inner_d.addCallback(self.format_blob_infos)
                inner_d.addCallback(set_field)
                return inner_d

            if 'reference' in further_blobs_request:
                d = self.get_stream_hash_from_reference(further_blobs_request['reference'])
                d.addCallback(get_further_blobs)
                return d
            else:
                response['further_blobs'] = {'error': 'NO_REFERENCE_SENT'}
                return defer.succeed(response)
        else:
            return defer.succeed({})

    ######### internal #########

    def handle_blob_info_payment_rate(self, requested_payment_rate):
        if not self.payment_rate_manager.accept_rate_live_blob_info(self.peer, requested_payment_rate):
            return False
        else:
            self.blob_info_payment_rate = requested_payment_rate
            return True

    def format_blob_infos(self, blobs):
        blob_infos = []
        for blob_hash, blob_num, revision, iv, length, signature in blobs:
            blob_info = {}
            if length != 0:
                blob_info['blob_hash'] = blob_hash
            blob_info['blob_num'] = blob_num
            blob_info['revision'] = revision
            blob_info['iv'] = iv
            blob_info['length'] = length
            blob_info['signature'] = signature
            blob_infos.append(blob_info)
        return blob_infos

    def get_stream_hash_from_reference(self, reference):
        d = self.stream_info_manager.check_if_stream_exists(reference)

        def check_if_stream_found(result):
            if result is True:
                return reference
            else:
                return self.stream_info_manager.get_stream_of_blob(reference)

        d.addCallback(check_if_stream_found)
        return d

    def get_further_blobs(self, stream_hash, start, end, count):
        ds = []
        if start is not None and start != "beginning":
            ds.append(self.stream_info_manager.get_stream_of_blob(start))
        if end is not None and end != 'end':
            ds.append(self.stream_info_manager.get_stream_of_blob(end))
        dl = defer.DeferredList(ds, fireOnOneErrback=True)

        def ensure_streams_match(results):
            for success, stream_of_blob in results:
                if stream_of_blob != stream_hash:
                    raise ValueError("Blob does not match stream")
            return True

        def get_blob_infos():
            reverse = False
            count_to_use = count
            if start is None:
                reverse = True
            elif end is not None and count_to_use is not None and count_to_use < 0:
                reverse = True
            if count_to_use is not None and count_to_use < 0:
                count_to_use *= -1
            if start == "beginning" or start is None:
                s = None
            else:
                s = start
            if end == "end" or end is None:
                e = None
            else:
                e = end
            return self.stream_info_manager.get_blobs_for_stream(stream_hash, s, e, count_to_use, reverse)

        dl.addCallback(ensure_streams_match)
        dl.addCallback(lambda _: get_blob_infos())
        return dl