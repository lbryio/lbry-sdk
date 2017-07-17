import logging
from twisted.internet import interfaces, defer
from zope.interface import implements


log = logging.getLogger(__name__)


class StreamCreator(object):
    """Classes which derive from this class create a 'stream', which can be any
        collection of associated blobs and associated metadata. These classes
        use the IConsumer interface to get data from an IProducer and transform
        the data into a 'stream'"""

    implements(interfaces.IConsumer)

    def __init__(self, name):
        """
        @param name: the name of the stream
        """
        self.name = name
        self.stopped = True
        self.producer = None
        self.streaming = None
        self.blob_count = -1
        self.current_blob = None
        self.finished_deferreds = []

    def _blob_finished(self, blob_info):
        pass

    def registerProducer(self, producer, streaming):

        from twisted.internet import reactor

        self.producer = producer
        self.streaming = streaming
        self.stopped = False
        if streaming is False:
            reactor.callLater(0, self.producer.resumeProducing)

    def unregisterProducer(self):
        self.stopped = True
        self.producer = None

    def stop(self):
        """Stop creating the stream. Create the terminating zero-length blob."""
        log.debug("stop has been called for StreamCreator")
        self.stopped = True
        if self.current_blob is not None:
            current_blob = self.current_blob
            d = current_blob.close()
            d.addCallback(self._blob_finished)
            d.addErrback(self._error)
            self.finished_deferreds.append(d)
            self.current_blob = None
        self._finalize()
        dl = defer.DeferredList(self.finished_deferreds)
        dl.addCallback(lambda _: self._finished())
        dl.addErrback(self._error)
        return dl

    def _error(self, error):
        log.error(error)

    def _finalize(self):
        pass

    def _finished(self):
        pass

    # TODO: move the stream creation process to its own thread and
    #       remove the reactor from this process.
    def write(self, data):
        from twisted.internet import reactor
        self._write(data)
        if self.stopped is False and self.streaming is False:
            reactor.callLater(0, self.producer.resumeProducing)

    def _write(self, data):
        pass
