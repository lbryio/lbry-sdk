"""
Utility for creating Crypt Streams, which are encrypted blobs and associated metadata.
"""

import logging

from Crypto import Random
from Crypto.Cipher import AES

from twisted.internet import defer
from lbrynet.core.StreamCreator import StreamCreator
from lbrynet.cryptstream.CryptBlob import CryptStreamBlobMaker


log = logging.getLogger(__name__)


class CryptStreamCreator(StreamCreator):
    """Create a new stream with blobs encrypted by a symmetric cipher.

    Each blob is encrypted with the same key, but each blob has its
    own initialization vector which is associated with the blob when
    the blob is associated with the stream.
    """
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
        StreamCreator.__init__(self, name)
        self.blob_manager = blob_manager
        self.key = key
        if iv_generator is None:
            self.iv_generator = self.random_iv_generator()
        else:
            self.iv_generator = iv_generator

    @staticmethod
    def random_iv_generator():
        while 1:
            yield Random.new().read(AES.block_size)

    def setup(self):
        """Create the symmetric key if it wasn't provided"""

        if self.key is None:
            self.key = Random.new().read(AES.block_size)

        return defer.succeed(True)

    def _finalize(self):
        """
        Finalize a stream by adding an empty
        blob at the end, this is to indicate that
        the stream has ended. This empty blob is not
        saved to the blob manager
        """
        log.debug("_finalize has been called")
        self.blob_count += 1
        iv = self.iv_generator.next()
        final_blob_creator = self.blob_manager.get_blob_creator()
        final_blob = self._get_blob_maker(iv, final_blob_creator)
        d = final_blob.close()
        d.addCallback(self._blob_finished)
        self.finished_deferreds.append(d)

    def _write(self, data):
        def close_blob(blob):
            d = blob.close()
            d.addCallback(self._blob_finished)
            self.finished_deferreds.append(d)

        while len(data) > 0:
            if self.current_blob is None:
                self.next_blob_creator = self.blob_manager.get_blob_creator()
                self.blob_count += 1
                iv = self.iv_generator.next()
                self.current_blob = self._get_blob_maker(iv, self.next_blob_creator)
            done, num_bytes_written = self.current_blob.write(data)
            data = data[num_bytes_written:]
            if done is True:
                d = self.current_blob.close()
                d.addCallback(self._blob_finished)
                d.addCallback(lambda _: self.blob_manager.creator_finished(self.next_blob_creator))
                self.finished_deferreds.append(d)
                self.current_blob = None

    def _get_blob_maker(self, iv, blob_creator):
        return CryptStreamBlobMaker(self.key, iv, self.blob_count, blob_creator)
