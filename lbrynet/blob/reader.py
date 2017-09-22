import logging
from twisted.internet import interfaces
from zope.interface import implements

log = logging.getLogger(__name__)


class HashBlobReader(object):
    implements(interfaces.IConsumer)

    def __init__(self, write_func):
        self.write_func = write_func

    def registerProducer(self, producer, streaming):
        from twisted.internet import reactor

        self.producer = producer
        self.streaming = streaming
        if self.streaming is False:
            reactor.callLater(0, self.producer.resumeProducing)

    def unregisterProducer(self):
        pass

    def write(self, data):
        from twisted.internet import reactor

        self.write_func(data)
        if self.streaming is False:
            reactor.callLater(0, self.producer.resumeProducing)
