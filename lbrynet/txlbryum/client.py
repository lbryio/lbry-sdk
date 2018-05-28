import json
import logging
import socket

from twisted.internet import defer, error
from twisted.protocols.basic import LineOnlyReceiver
from errors import RemoteServiceException, ProtocolException, ServiceException

log = logging.getLogger(__name__)


class StratumClientProtocol(LineOnlyReceiver):
    delimiter = '\n'

    def __init__(self):
        self._connected = defer.Deferred()

    def _get_id(self):
        self.request_id += 1
        return self.request_id

    def _get_ip(self):
        return self.transport.getPeer().host

    def get_session(self):
        return self.session

    def connectionMade(self):
        try:
            self.transport.setTcpNoDelay(True)
            self.transport.setTcpKeepAlive(True)
            if hasattr(socket, "TCP_KEEPIDLE"):
                self.transport.socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPIDLE,
                                                 120)  # Seconds before sending keepalive probes
            else:
                log.debug("TCP_KEEPIDLE not available")
            if hasattr(socket, "TCP_KEEPINTVL"):
                self.transport.socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPINTVL,
                                                 1)  # Interval in seconds between keepalive probes
            else:
                log.debug("TCP_KEEPINTVL not available")
            if hasattr(socket, "TCP_KEEPCNT"):
                self.transport.socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPCNT,
                                                 5)  # Failed keepalive probles before declaring other end dead
            else:
                log.debug("TCP_KEEPCNT not available")

        except Exception as err:
            # Supported only by the socket transport,
            # but there's really no better place in code to trigger this.
            log.warning("Error setting up socket: %s", err)

        self.request_id = 0
        self.lookup_table = {}

        self._connected.callback(True)

        # Initiate connection session
        self.session = {}

        log.debug("Connected %s" % self.transport.getPeer().host)

    def transport_write(self, data):
        '''Overwrite this if transport needs some extra care about data written
        to the socket, like adding message format in websocket.'''
        try:
            self.transport.write(data)
        except AttributeError:
            # Transport is disconnected
            log.warning("transport is disconnected")

    def writeJsonRequest(self, method, params, is_notification=False):
        request_id = None if is_notification else self._get_id()
        serialized = json.dumps({'id': request_id, 'method': method, 'params': params})
        self.transport_write("%s\n" % serialized)
        return request_id

    def writeJsonResponse(self, data, message_id):
        serialized = json.dumps({'id': message_id, 'result': data, 'error': None})
        self.transport_write("%s\n" % serialized)

    def writeJsonError(self, code, message, traceback, message_id):
        serialized = json.dumps(
            {'id': message_id, 'result': None, 'error': (code, message, traceback)}
        )
        self.transport_write("%s\n" % serialized)

    def writeGeneralError(self, message, code=-1):
        log.error(message)
        return self.writeJsonError(code, message, None, None)

    def process_response(self, data, message_id):
        self.writeJsonResponse(data.result, message_id)

    def process_failure(self, failure, message_id):
        if not isinstance(failure.value, ServiceException):
            # All handled exceptions should inherit from ServiceException class.
            # Throwing other exception class means that it is unhandled error
            # and we should log it.
            log.exception(failure)
        code = getattr(failure.value, 'code', -1)
        if message_id != None:
            tb = failure.getBriefTraceback()
            self.writeJsonError(code, failure.getErrorMessage(), tb, message_id)

    def dataReceived(self, data):
        '''Original code from Twisted, hacked for request_counter proxying.
        request_counter is hack for HTTP transport, didn't found cleaner solution how
        to indicate end of request processing in asynchronous manner.

        TODO: This would deserve some unit test to be sure that future twisted versions
        will work nicely with this.'''

        lines = (self._buffer + data).split(self.delimiter)
        self._buffer = lines.pop(-1)

        for line in lines:
            if self.transport.disconnecting:
                return
            if len(line) > self.MAX_LENGTH:
                return self.lineLengthExceeded(line)
            else:
                try:
                    self.lineReceived(line)
                except Exception as exc:
                    # log.exception("Processing of message failed")
                    log.warning("Failed message: %s from %s" % (str(exc), self._get_ip()))
                    return error.ConnectionLost('Processing of message failed')

        if len(self._buffer) > self.MAX_LENGTH:
            return self.lineLengthExceeded(self._buffer)

    def lineReceived(self, line):
        try:
            message = json.loads(line)
        except (ValueError, TypeError):
            # self.writeGeneralError("Cannot decode message '%s'" % line)
            raise ProtocolException("Cannot decode message '%s'" % line.strip())
        msg_id = message.get('id', 0)
        msg_result = message.get('result')
        msg_error = message.get('error')
        if msg_id:
            # It's a RPC response
            # Perform lookup to the table of waiting requests.
            try:
                meta = self.lookup_table[msg_id]
                del self.lookup_table[msg_id]
            except KeyError:
                # When deferred object for given message ID isn't found, it's an error
                raise ProtocolException(
                    "Lookup for deferred object for message ID '%s' failed." % msg_id)
            # If there's an error, handle it as errback
            # If both result and error are null, handle it as a success with blank result
            if msg_error != None:
                meta['defer'].errback(
                    RemoteServiceException(msg_error[0], msg_error[1], msg_error[2])
                )
            else:
                meta['defer'].callback(msg_result)
        else:
            raise ProtocolException("Cannot handle message '%s'" % line)

    def rpc(self, method, params, is_notification=False):
        '''
            This method performs remote RPC call.

            If method should expect an response, it store
            request ID to lookup table and wait for corresponding
            response message.
        '''

        request_id = self.writeJsonRequest(method, params, is_notification)
        if is_notification:
            return
        d = defer.Deferred()
        self.lookup_table[request_id] = {'defer': d, 'method': method, 'params': params}
        return d
