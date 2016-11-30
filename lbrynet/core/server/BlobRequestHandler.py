import logging

from twisted.internet import defer
from twisted.protocols.basic import FileSender
from twisted.python.failure import Failure
from zope.interface import implements


from lbrynet.core.Offer import Offer
from lbrynet import analytics
from lbrynet.interfaces import IQueryHandlerFactory, IQueryHandler, IBlobSender


log = logging.getLogger(__name__)


class BlobRequestHandlerFactory(object):
    implements(IQueryHandlerFactory)

    def __init__(self, blob_manager, wallet, payment_rate_manager, track):
        self.blob_manager = blob_manager
        self.wallet = wallet
        self.payment_rate_manager = payment_rate_manager
        self.track = track

    ######### IQueryHandlerFactory #########

    def build_query_handler(self):
        q_h = BlobRequestHandler(
            self.blob_manager, self.wallet, self.payment_rate_manager, self.track)
        return q_h

    def get_primary_query_identifier(self):
        return 'requested_blob'

    def get_description(self):
        return "Blob Uploader - uploads blobs"


class BlobRequestHandler(object):
    implements(IQueryHandler, IBlobSender)
    PAYMENT_RATE_QUERY = 'blob_data_payment_rate'
    BLOB_QUERY = 'requested_blob'
    AVAILABILITY_QUERY = 'requested_blobs'

    def __init__(self, blob_manager, wallet, payment_rate_manager, track):
        self.blob_manager = blob_manager
        self.payment_rate_manager = payment_rate_manager
        self.wallet = wallet
        self.query_identifiers = [self.PAYMENT_RATE_QUERY, self.BLOB_QUERY, self.AVAILABILITY_QUERY]
        self.track = track
        self.peer = None
        self.blob_data_payment_rate = None
        self.read_handle = None
        self.currently_uploading = None
        self.file_sender = None
        self.blob_bytes_uploaded = 0
        self._blobs_requested = []

    ######### IQueryHandler #########

    def register_with_request_handler(self, request_handler, peer):
        self.peer = peer
        request_handler.register_query_handler(self, self.query_identifiers)
        request_handler.register_blob_sender(self)

    def handle_queries(self, queries):
        response = defer.succeed({})
        log.debug("Handle query: %s", str(queries))

        if self.AVAILABILITY_QUERY in queries:
            self._blobs_requested = queries[self.AVAILABILITY_QUERY]
            response.addCallback(lambda r: self._reply_to_availability(r, self._blobs_requested))
        if self.PAYMENT_RATE_QUERY in queries:
            offered_rate = queries[self.PAYMENT_RATE_QUERY]
            offer = Offer(offered_rate)
            if offer.rate is None:
                log.warning("Empty rate offer")
            response.addCallback(lambda r: self._handle_payment_rate_query(offer, r))
        if self.BLOB_QUERY in queries:
            incoming = queries[self.BLOB_QUERY]
            response.addCallback(lambda r: self._reply_to_send_request(r, incoming))
        return response

    ######### IBlobSender #########

    def send_blob_if_requested(self, consumer):
        if self.currently_uploading is not None:
            return self.send_file(consumer)
        return defer.succeed(True)

    def cancel_send(self, err):
        if self.currently_uploading is not None:
            self.currently_uploading.close_read_handle(self.read_handle)
        self.read_handle = None
        self.currently_uploading = None
        return err

    ######### internal #########

    def _reply_to_availability(self, request, blobs):
        d = self._get_available_blobs(blobs)

        def set_available(available_blobs):
            log.debug("available blobs: %s", str(available_blobs))
            request.update({'available_blobs': available_blobs})
            return request

        d.addCallback(set_available)
        return d

    def _handle_payment_rate_query(self, offer, request):
        blobs = self._blobs_requested
        log.debug("Offered rate %f LBC/mb for %i blobs", offer.rate, len(blobs))
        reply = self.payment_rate_manager.reply_to_offer(self.peer, blobs, offer)
        if reply.is_accepted:
            self.blob_data_payment_rate = offer.rate
            request[self.PAYMENT_RATE_QUERY] = "RATE_ACCEPTED"
            log.debug("Accepted rate: %f", offer.rate)
        elif reply.is_too_low:
            request[self.PAYMENT_RATE_QUERY] = "RATE_TOO_LOW"
            log.debug("Reject rate: %f", offer.rate)
        elif reply.is_unset:
            log.warning("Rate unset")
            request['incoming_blob'] = {'error': 'RATE_UNSET'}
        log.debug("Returning rate query result: %s", str(request))

        return request

    def _handle_blob_query(self, response, query):
        log.debug("Received the client's request to send a blob")
        response['incoming_blob'] = {}

        if self.blob_data_payment_rate is None:
            response['incoming_blob'] = {'error': "RATE_UNSET"}
            return response
        else:
            return self._send_blob(response, query)

    def _send_blob(self, response, query):
        d = self.blob_manager.get_blob(query, True)
        d.addCallback(self.open_blob_for_reading, response)
        return d

    def open_blob_for_reading(self, blob, response):
        response_fields = {}
        d = defer.succeed(None)
        if blob.is_validated():
            read_handle = blob.open_for_reading()
            if read_handle is not None:
                self.currently_uploading = blob
                self.read_handle = read_handle
                log.info("Sending %s to client", str(blob))
                response_fields['blob_hash'] = blob.blob_hash
                response_fields['length'] = blob.length
                response['incoming_blob'] = response_fields
                d.addCallback(lambda _: self.record_transaction(blob))
                d.addCallback(lambda _: response)
                return d
        log.debug("We can not send %s", str(blob))
        response['incoming_blob'] = {'error': 'BLOB_UNAVAILABLE'}
        d.addCallback(lambda _: response)
        return d

    def record_transaction(self, blob):
        d = self.blob_manager.add_blob_to_upload_history(
            str(blob), self.peer.host, self.blob_data_payment_rate)
        return d

    def _reply_to_send_request(self, response, incoming):
        response_fields = {}
        response['incoming_blob'] = response_fields

        if self.blob_data_payment_rate is None:
            log.debug("Rate not set yet")
            response['incoming_blob'] = {'error': 'RATE_UNSET'}
            return defer.succeed(response)
        else:
            log.debug("Requested blob: %s", str(incoming))
            d = self.blob_manager.get_blob(incoming, True)
            d.addCallback(lambda blob: self.open_blob_for_reading(blob, response))
            return d

    def _get_available_blobs(self, requested_blobs):
        d = self.blob_manager.completed_blobs(requested_blobs)
        return d

    def send_file(self, consumer):

        def _send_file():
            inner_d = start_transfer()
            # TODO: if the transfer fails, check if it's because the connection was cut off.
            # TODO: if so, perhaps bill the client
            inner_d.addCallback(lambda _: set_expected_payment())
            inner_d.addBoth(set_not_uploading)
            return inner_d

        def count_bytes(data):
            uploaded = len(data)
            self.blob_bytes_uploaded += uploaded
            self.peer.update_stats('blob_bytes_uploaded', uploaded)
            self.track.add_observation(analytics.BLOB_BYTES_UPLOADED, uploaded)
            return data

        def start_transfer():
            self.file_sender = FileSender()
            log.debug("Starting the file upload")
            assert self.read_handle is not None, \
                "self.read_handle was None when trying to start the transfer"
            d = self.file_sender.beginFileTransfer(self.read_handle, consumer, count_bytes)
            return d

        def set_expected_payment():
            log.debug("Setting expected payment")
            if self.blob_bytes_uploaded != 0 and self.blob_data_payment_rate is not None:
                # TODO: explain why 2**20
                self.wallet.add_expected_payment(self.peer,
                                                 self.currently_uploading.length * 1.0 *
                                                 self.blob_data_payment_rate / 2**20)
                self.blob_bytes_uploaded = 0
            self.peer.update_stats('blobs_uploaded', 1)
            return None

        def set_not_uploading(reason=None):
            if self.currently_uploading is not None:
                self.currently_uploading.close_read_handle(self.read_handle)
                self.read_handle = None
                self.currently_uploading = None
            self.file_sender = None
            if reason is not None and isinstance(reason, Failure):
                log.warning("Upload has failed. Reason: %s", reason.getErrorMessage())

        return _send_file()
