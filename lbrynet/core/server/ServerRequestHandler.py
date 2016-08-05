import json
import logging
from twisted.internet import interfaces, defer
from zope.interface import implements
from lbrynet.interfaces import IRequestHandler


log = logging.getLogger(__name__)


class ServerRequestHandler(object):
    """This class handles requests from clients. It can upload blobs and return request for information about
    more blobs that are associated with streams"""

    implements(interfaces.IPushProducer, interfaces.IConsumer, IRequestHandler)

    def __init__(self, consumer):
        self.consumer = consumer
        self.production_paused = False
        self.request_buff = ''
        self.response_buff = ''
        self.producer = None
        self.request_received = False
        self.CHUNK_SIZE = 2**14
        self.query_handlers = {}  # {IQueryHandler: [query_identifiers]}
        self.blob_sender = None
        self.consumer.registerProducer(self, True)

    #IPushProducer stuff

    def pauseProducing(self):
        self.production_paused = True

    def stopProducing(self):
        if self.producer is not None:
            self.producer.stopProducing()
            self.producer = None
        self.production_paused = True
        self.consumer.unregisterProducer()

    def resumeProducing(self):

        from twisted.internet import reactor

        self.production_paused = False
        self._produce_more()
        if self.producer is not None:
            reactor.callLater(0, self.producer.resumeProducing)

    def _produce_more(self):

        from twisted.internet import reactor

        if self.production_paused is False:
            chunk = self.response_buff[:self.CHUNK_SIZE]
            self.response_buff = self.response_buff[self.CHUNK_SIZE:]
            if chunk != '':
                log.debug("writing %s bytes to the client", str(len(chunk)))
                self.consumer.write(chunk)
                reactor.callLater(0, self._produce_more)

    #IConsumer stuff

    def registerProducer(self, producer, streaming):
        #assert self.file_sender == producer
        self.producer = producer
        assert streaming is False
        producer.resumeProducing()

    def unregisterProducer(self):
        self.producer = None

    def write(self, data):

        from twisted.internet import reactor

        self.response_buff = self.response_buff + data
        self._produce_more()

        def get_more_data():
            if self.producer is not None:
                log.debug("Requesting more data from the producer")
                self.producer.resumeProducing()

        reactor.callLater(0, get_more_data)

    #From Protocol

    def data_received(self, data):
        log.debug("Received data")
        log.debug("%s", str(data))
        if self.request_received is False:
            self.request_buff = self.request_buff + data
            msg = self.try_to_parse_request(self.request_buff)
            if msg is not None:
                self.request_buff = ''
                d = self.handle_request(msg)
                if self.blob_sender is not None:
                    d.addCallback(lambda _: self.blob_sender.send_blob_if_requested(self))
                d.addCallbacks(lambda _: self.finished_response(), self.request_failure_handler)
            else:
                log.info("Request buff not a valid json message")
                log.info("Request buff: %s", str(self.request_buff))
        else:
            log.warning("The client sent data when we were uploading a file. This should not happen")

    ######### IRequestHandler #########

    def register_query_handler(self, query_handler, query_identifiers):
        self.query_handlers[query_handler] = query_identifiers

    def register_blob_sender(self, blob_sender):
        self.blob_sender = blob_sender

    #response handling

    def request_failure_handler(self, err):
        log.warning("An error occurred handling a request. Error: %s", err.getErrorMessage())
        self.stopProducing()
        return err

    def finished_response(self):
        self.request_received = False
        self._produce_more()

    def send_response(self, msg):
        m = json.dumps(msg)
        log.debug("Sending a response of length %s", str(len(m)))
        log.debug("Response: %s", str(m))
        self.response_buff = self.response_buff + m
        self._produce_more()
        return True

    def handle_request(self, msg):
        log.debug("Handling a request")
        log.debug(str(msg))

        def create_response_message(results):
            response = {}
            for success, result in results:
                if success is True:
                    response.update(result)
                else:
                    # result is a Failure
                    return result
            log.debug("Finished making the response message. Response: %s", str(response))
            return response

        def log_errors(err):
            log.warning("An error occurred handling a client request. Error message: %s", err.getErrorMessage())
            return err

        def send_response(response):
            self.send_response(response)
            return True

        ds = []
        for query_handler, query_identifiers in self.query_handlers.iteritems():
            queries = {q_i: msg[q_i] for q_i in query_identifiers if q_i in msg}
            d = query_handler.handle_queries(queries)
            d.addErrback(log_errors)
            ds.append(d)

        dl = defer.DeferredList(ds)
        dl.addCallback(create_response_message)
        dl.addCallback(send_response)
        return dl

    def try_to_parse_request(self, request_buff):
        try:
            msg = json.loads(request_buff)
            return msg
        except ValueError:
            return None
