import json
import logging
from decimal import Decimal
from twisted.internet import error, defer
from twisted.internet.protocol import Protocol, ClientFactory
from twisted.protocols.policies import TimeoutMixin
from twisted.python import failure
from lbrynet import conf, utils
from lbrynet.error import ConnectionClosedBeforeResponseError, NoResponseError
from lbrynet.error import DownloadCancelledError, MisbehavingPeerError
from lbrynet.error import RequestCanceledError


log = logging.getLogger(__name__)


def encode_decimal(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(repr(obj) + " is not JSON serializable")


class ClientProtocol(Protocol, TimeoutMixin):
    #implements(IRequestSender, IRateLimited)
    ######### Protocol #########
    PROTOCOL_TIMEOUT = 30

    def connectionMade(self):
        log.debug("Connection made to %s", self.factory.peer)
        self._connection_manager = self.factory.connection_manager
        self._rate_limiter = self.factory.rate_limiter
        self.peer = self.factory.peer
        self._response_deferreds = {}
        self._response_buff = b''
        self._downloading_blob = False
        self._blob_download_request = None
        self._next_request = {}
        self.connection_closed = False
        self.connection_closing = False
        # This needs to be set for TimeoutMixin
        self.callLater = utils.call_later
        self.peer.report_up()

        self._ask_for_request()

    def dataReceived(self, data):
        log.debug("Received %d bytes from %s", len(data), self.peer)
        self.setTimeout(None)
        self._rate_limiter.report_dl_bytes(len(data))

        if self._downloading_blob is True:
            self._blob_download_request.write(data)
        else:
            self._response_buff += data
            if len(self._response_buff) > conf.settings['MAX_RESPONSE_INFO_SIZE']:
                log.warning("Response is too large from %s. Size %s",
                            self.peer, len(self._response_buff))
                self.transport.loseConnection()
            response, extra_data = self._get_valid_response(self._response_buff)
            if response is not None:
                self._response_buff = b''
                self._handle_response(response)
                if self._downloading_blob is True and len(extra_data) != 0:
                    self._blob_download_request.write(extra_data)

    def timeoutConnection(self):
        log.info("Connection timed out to %s", self.peer)
        self.peer.report_down()
        self.transport.abortConnection()

    def connectionLost(self, reason=None):
        log.debug("Connection lost to %s: %s", self.peer, reason)
        self.setTimeout(None)
        self.connection_closed = True
        if reason is None or reason.check(error.ConnectionDone):
            err = failure.Failure(ConnectionClosedBeforeResponseError())
        else:
            err = reason
        for key, d in self._response_deferreds.items():
            d.errback(err)
        self._response_deferreds.clear()
        if self._blob_download_request is not None:
            self._blob_download_request.cancel(err)
        self.factory.connection_was_made_deferred.callback(True)

    ######### IRequestSender #########

    def add_request(self, request):
        if request.response_identifier in self._response_deferreds:
            raise ValueError("There is already a request for that response active")
        self._next_request.update(request.request_dict)
        d = defer.Deferred()
        log.debug("Adding a request for %s. Request: %s", self.peer, request.request_dict)
        self._response_deferreds[request.response_identifier] = d
        return d

    def add_blob_request(self, blob_request):
        if self._blob_download_request is None:
            d = self.add_request(blob_request)
            self._blob_download_request = blob_request
            blob_request.finished_deferred.addCallbacks(self._downloading_finished,
                                                        self._handle_response_error)
            return d
        else:
            return defer.fail(ValueError("There is already a blob download request active"))

    def cancel_requests(self):
        self.connection_closing = True
        ds = []
        err = RequestCanceledError()
        for key, d in list(self._response_deferreds.items()):
            del self._response_deferreds[key]
            d.errback(err)
            ds.append(d)
        if self._blob_download_request is not None:
            ds.append(self._blob_download_request.finished_deferred)
            self._blob_download_request.cancel(err)
            self._blob_download_request = None
        self._downloading_blob = False
        return defer.DeferredList(ds)

    ######### Internal request handling #########

    def _handle_request_error(self, err):
        log.error("An unexpected error occurred creating or sending a request to %s. %s: %s",
                  self.peer, err.type, err)
        self.transport.loseConnection()

    def _ask_for_request(self):
        if self.connection_closed is True or self.connection_closing is True:
            return

        def send_request_or_close(do_request):
            if do_request is True:
                request_msg, self._next_request = self._next_request, {}
                self._send_request_message(request_msg)
            else:
                # The connection manager has indicated that this connection should be terminated
                log.debug("Closing the connection to %s due to having no further requests to send",
                          self.peer)
                self.peer.report_success()
                self.transport.loseConnection()
        d = self._connection_manager.get_next_request(self.peer, self)
        d.addCallback(send_request_or_close)
        d.addErrback(self._handle_request_error)

    def _send_request_message(self, request_msg):
        self.setTimeout(self.PROTOCOL_TIMEOUT)
        # TODO: compare this message to the last one. If they're the same,
        # TODO: incrementally delay this message.
        m = json.dumps(request_msg, default=encode_decimal).encode()
        self.transport.write(m)

    def _get_valid_response(self, response_msg):
        extra_data = None
        response = None
        curr_pos = 0
        while 1:
            next_close_paren = response_msg.find(b'}', curr_pos)
            if next_close_paren != -1:
                curr_pos = next_close_paren + 1
                try:
                    response = json.loads(response_msg[:curr_pos])
                except ValueError:
                    pass
                else:
                    extra_data = response_msg[curr_pos:]
                    break
            else:
                break
        return response, extra_data

    def _handle_response_error(self, err):
        # If an error gets to this point, log it and kill the connection.
        if err.check(DownloadCancelledError, RequestCanceledError, error.ConnectionAborted,
                     ConnectionClosedBeforeResponseError):
            # TODO: (wish-list) it seems silly to close the connection over this, and it shouldn't
            # TODO: always be this way. it's done this way now because the client has no other way
            # TODO: of telling the server it wants the download to stop. It would be great if the
            # TODO: protocol had such a mechanism.
            log.info("Closing the connection to %s because the download of blob %s was canceled",
                     self.peer, self._blob_download_request.blob)
            result = None
        elif err.check(MisbehavingPeerError):
            log.warning("The connection to %s is closing due to: %s", self.peer, err)
            result = err
        else:
            log.error("The connection to %s is closing due to an unexpected error: %s",
                      self.peer, err)
            result = err
        self._blob_download_request = None
        self._downloading_blob = False
        self.transport.loseConnection()
        return result

    def _handle_response(self, response):
        ds = []
        log.debug(
            "Handling a response from %s. Expected responses: %s. Actual responses: %s",
            self.peer, self._response_deferreds.keys(), response.keys())
        for key, val in response.items():
            if key in self._response_deferreds:
                d = self._response_deferreds.pop(key)
                d.callback({key: val})
                ds.append(d)
        for k, d in self._response_deferreds.items():
            del self._response_deferreds[k]
            d.errback(failure.Failure(NoResponseError()))
            ds.append(d)

        if self._blob_download_request is not None:
            self._downloading_blob = True
            d = self._blob_download_request.finished_deferred
            d.addErrback(self._handle_response_error)
            ds.append(d)

        # TODO: are we sure we want to consume errors here
        dl = defer.DeferredList(ds, consumeErrors=True)

        def get_next_request(results):
            failed = False
            for success, result in results:
                if success is False:
                    failed = True
                    if not isinstance(result.value, DownloadCancelledError):
                        log.info(result.value)
                        log.info("The connection to %s is closing due to an error: %s",
                                 self.peer, result.getTraceback())

                        self.peer.report_down()
            if failed is False:
                log.debug("Asking for another request from %s", self.peer)
                self._ask_for_request()
            else:
                log.warning("Not asking for another request from %s", self.peer)
                self.transport.loseConnection()

        dl.addCallback(get_next_request)

    def _downloading_finished(self, arg):
        log.debug("The blob has finished downloading from %s", self.peer)
        self._blob_download_request = None
        self._downloading_blob = False
        return arg

    ######### IRateLimited #########

    def throttle_upload(self):
        pass

    def unthrottle_upload(self):
        pass

    def throttle_download(self):
        self.transport.pauseProducing()

    def unthrottle_download(self):
        self.transport.resumeProducing()


class ClientProtocolFactory(ClientFactory):
    protocol = ClientProtocol

    def __init__(self, peer, rate_limiter, connection_manager):
        self.peer = peer
        self.rate_limiter = rate_limiter
        self.connection_manager = connection_manager
        self.p = None
        # This defer fires and returns True when connection was
        # made and completed, or fires and returns False if
        # connection failed
        self.connection_was_made_deferred = defer.Deferred()

    def clientConnectionFailed(self, connector, reason):
        log.debug("Connection failed to %s: %s", self.peer, reason)
        self.peer.report_down()
        self.connection_was_made_deferred.callback(False)

    def buildProtocol(self, addr):
        p = self.protocol()
        p.factory = self
        self.p = p
        return p
