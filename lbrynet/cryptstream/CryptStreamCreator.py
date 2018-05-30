"""
Utility for creating Crypt Streams, which are encrypted blobs and associated metadata.
"""
import os
import logging

from cryptography.hazmat.primitives.ciphers.algorithms import AES
from twisted.internet import interfaces, defer
from zope.interface import implements
from lbrynet.cryptstream.CryptBlob import CryptStreamBlobMaker


log = logging.getLogger(__name__)


class CryptStreamCreator(object):
    """
    Create a new stream with blobs encrypted by a symmetric cipher.

    Each blob is encrypted with the same key, but each blob has its
    own initialization vector which is associated with the blob when
    the blob is associated with the stream.
    """

    implements(interfaces.IConsumer)

    def __init__(self, blob_manager, name=None, key=None, iv_generator=None):
        """@param blob_manager: Object that stores and provides access to blobs.
        @type blob_manager: BlobManager

        @param name: the name of the stream, which will be presented to the user
        @type name: string

        @param key: the raw AES key which will be used to encrypt the
            blobs. If None, a random key will be generated.
        @type key: string

        @param iv_generator: a generator which yields initialization
            vectors for the blobs. Will be called once for each blob.
        @type iv_generator: a generator function which yields strings

        @return: None
        """
        self.blob_manager = blob_manager
        self.name = name
        self.key = key
        if iv_generator is None:
            self.iv_generator = self.random_iv_generator()
        else:
            self.iv_generator = iv_generator

        self.stopped = True
        self.producer = None
        self.streaming = None
        self.blob_count = -1
        self.current_blob = None
        self.finished_deferreds = []

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

    def _close_current_blob(self):
        # close the blob that was being written to
        # and save it to blob manager
        should_announce = self.blob_count == 0
        d = self.current_blob.close()
        d.addCallback(self._blob_finished)
        d.addCallback(lambda blob_info: self.blob_manager.creator_finished(blob_info,
                                                                   should_announce))
        self.finished_deferreds.append(d)
        self.current_blob = None

    def stop(self):
        """Stop creating the stream. Create the terminating zero-length blob."""
        log.debug("stop has been called for StreamCreator")
        self.stopped = True
        if self.current_blob is not None:
            self._close_current_blob()
        d = self._finalize()
        d.addCallback(lambda _: self._finished())
        return d

    # TODO: move the stream creation process to its own thread and
    #       remove the reactor from this process.
    def write(self, data):
        from twisted.internet import reactor
        self._write(data)
        if self.stopped is False and self.streaming is False:
            reactor.callLater(0, self.producer.resumeProducing)

    @staticmethod
    def random_iv_generator():
        while 1:
            yield os.urandom(AES.block_size / 8)

    def setup(self):
        """Create the symmetric key if it wasn't provided"""

        if self.key is None:
            self.key = os.urandom(AES.block_size / 8)

        return defer.succeed(True)

    @defer.inlineCallbacks
    def _finalize(self):
        """
        Finalize a stream by adding an empty
        blob at the end, this is to indicate that
        the stream has ended. This empty blob is not
        saved to the blob manager
        """

        yield defer.DeferredList(self.finished_deferreds)
        self.blob_count += 1
        iv = self.iv_generator.next()
        final_blob = self._get_blob_maker(iv, self.blob_manager.get_blob_creator())
        stream_terminator = yield final_blob.close()
        terminator_info = yield self._blob_finished(stream_terminator)
        defer.returnValue(terminator_info)

    def _write(self, data):
        while len(data) > 0:
            if self.current_blob is None:
                self.next_blob_creator = self.blob_manager.get_blob_creator()
                self.blob_count += 1
                iv = self.iv_generator.next()
                self.current_blob = self._get_blob_maker(iv, self.next_blob_creator)
            done, num_bytes_written = self.current_blob.write(data)
            data = data[num_bytes_written:]
            if done is True:
                self._close_current_blob()

    def _get_blob_maker(self, iv, blob_creator):
        return CryptStreamBlobMaker(self.key, iv, self.blob_count, blob_creator)

    def _finished(self):
        raise NotImplementedError()

    def _blob_finished(self, blob_info):
        raise NotImplementedError()
