import logging
from twisted.internet import defer
from twisted.protocols.basic import FileSender
from twisted.python.failure import Failure
from zope.interface import implements
from lbrynet.interfaces import IQueryHandlerFactory, IQueryHandler, IBlobSender


log = logging.getLogger(__name__)


class BlobRequestHandlerFactory(object):
    implements(IQueryHandlerFactory)

    def __init__(self, blob_manager, wallet, payment_rate_manager):
        self.blob_manager = blob_manager
        self.wallet = wallet
        self.payment_rate_manager = payment_rate_manager

    ######### IQueryHandlerFactory #########

    def build_query_handler(self):
        q_h = BlobRequestHandler(self.blob_manager, self.wallet, self.payment_rate_manager)
        return q_h

    def get_primary_query_identifier(self):
        return 'requested_blob'

    def get_description(self):
        return "Blob Uploader - uploads blobs"


class BlobRequestHandler(object):
    implements(IQueryHandler, IBlobSender)
    PAYMENT_RATE_QUERY = 'blob_data_payment_rate'
    BLOB_QUERY = 'requested_blob'

    def __init__(self, blob_manager, wallet, payment_rate_manager):
        self.blob_manager = blob_manager
        self.payment_rate_manager = payment_rate_manager
        self.wallet = wallet
        self.query_identifiers = [self.PAYMENT_RATE_QUERY, self.BLOB_QUERY]
        self.peer = None
        self.blob_data_payment_rate = None
        self.read_handle = None
        self.currently_uploading = None
        self.file_sender = None
        self.blob_bytes_uploaded = 0

    ######### IQueryHandler #########

    def register_with_request_handler(self, request_handler, peer):
        self.peer = peer
        request_handler.register_query_handler(self, self.query_identifiers)
        request_handler.register_blob_sender(self)

    def handle_queries(self, queries):
        response = {}
        if self.PAYMENT_RATE_QUERY in queries:
            self._handle_payment_rate_query(response, queries[self.PAYMENT_RATE_QUERY])
        if self.BLOB_QUERY in queries:
            return self._handle_blob_query(response, queries[self.BLOB_QUERY])
        else:
            return defer.succeed(response)

    def _handle_payment_rate_query(self, response, query):
        if not self.handle_blob_data_payment_rate(query):
            response['blob_data_payment_rate'] = "RATE_TOO_LOW"
        else:
            response['blob_data_payment_rate'] = 'RATE_ACCEPTED'

    def _handle_blob_query(self, response, query):
        log.debug("Received the client's request to send a blob")
        response['incoming_blob'] = {}

        if self.blob_data_payment_rate is None:
            response['incoming_blob']['error'] = "RATE_UNSET"
            return defer.succeed(response)
        else:
            return self._send_blob(response, query)

    def _send_blob(self, response, query):
        d = self.blob_manager.get_blob(query, True)
        d.addCallback(self.open_blob_for_reading, response)
        return d

    def open_blob_for_reading(self, blob, response):
        def failure(msg):
            log.warning("We can not send %s: %s", blob, msg)
            response['incoming_blob']['error'] = "BLOB_UNAVAILABLE"
            return response
        if not blob.is_validated():
            return failure("blob can't be validated")
        read_handle = blob.open_for_reading()
        if read_handle is None:
            return failure("blob can't be opened")

        self.currently_uploading = blob
        self.read_handle = read_handle
        log.info("Sending %s to client", blob)
        response['incoming_blob']['blob_hash'] = blob.blob_hash
        response['incoming_blob']['length'] = blob.length
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

    def handle_blob_data_payment_rate(self, requested_payment_rate):
        if not self.payment_rate_manager.accept_rate_blob_data(self.peer, requested_payment_rate):
            return False
        else:
            self.blob_data_payment_rate = requested_payment_rate
            return True

    def send_file(self, consumer):

        def _send_file():
            inner_d = start_transfer()
            # TODO: if the transfer fails, check if it's because the connection was cut off.
            # TODO: if so, perhaps bill the client
            inner_d.addCallback(lambda _: set_expected_payment())
            inner_d.addBoth(set_not_uploading)
            return inner_d

        def count_bytes(data):
            self.blob_bytes_uploaded += len(data)
            self.peer.update_stats('blob_bytes_uploaded', len(data))
            return data

        def start_transfer():
            self.file_sender = FileSender()
            log.debug("Starting the file upload")
            assert self.read_handle is not None, "self.read_handle was None when trying to start the transfer"
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
                log.info("Upload has failed. Reason: %s", reason.getErrorMessage())

        return _send_file()
