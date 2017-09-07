from io import BytesIO
import logging
import os
import threading
from twisted.internet import interfaces, defer, threads
from twisted.protocols.basic import FileSender
from twisted.web.client import FileBodyProducer
from twisted.python.failure import Failure
from zope.interface import implements
from lbrynet import conf
from lbrynet.core.Error import DownloadCanceledError, InvalidDataError
from lbrynet.core.cryptoutils import get_lbry_hash_obj
from lbrynet.core.utils import is_valid_blobhash


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


class HashBlobWriter(object):
    def __init__(self, write_handle, length_getter, finished_cb):
        self.write_handle = write_handle
        self.length_getter = length_getter
        self.finished_cb = finished_cb
        self._hashsum = get_lbry_hash_obj()
        self.len_so_far = 0

    @property
    def blob_hash(self):
        return self._hashsum.hexdigest()

    def write(self, data):
        self._hashsum.update(data)
        self.len_so_far += len(data)
        if self.len_so_far > self.length_getter():
            self.finished_cb(
                self,
                Failure(InvalidDataError("Length so far is greater than the expected length."
                                         " %s to %s" % (self.len_so_far,
                                                        self.length_getter()))))
        else:
            if self.write_handle is None:
                log.debug("Tried to write to a write_handle that was None.")
                return
            self.write_handle.write(data)
            if self.len_so_far == self.length_getter():
                self.finished_cb(self)

    def cancel(self, reason=None):
        if reason is None:
            reason = Failure(DownloadCanceledError())
        self.finished_cb(self, reason)


class HashBlob(object):
    """A chunk of data available on the network which is specified by a hashsum"""

    def __init__(self, blob_hash, length=None):
        assert is_valid_blobhash(blob_hash)
        self.blob_hash = blob_hash
        self.length = length
        self.writers = {}  # {Peer: writer, finished_deferred}
        self.finished_deferred = None
        self._verified = False
        self.readers = 0

    @property
    def verified(self):
        # protect verified from being modified by other classes
        return self._verified

    def set_length(self, length):
        if self.length is not None and length == self.length:
            return True
        if self.length is None and 0 <= length <= conf.settings['BLOB_SIZE']:
            self.length = length
            return True
        log.warning("Got an invalid length. Previous length: %s, Invalid length: %s",
                    self.length, length)
        return False

    def get_length(self):
        return self.length

    def is_validated(self):
        return bool(self._verified)

    def is_downloading(self):
        if self.writers:
            return True
        return False

    def read(self, write_func):
        def close_self(*args):
            self.close_read_handle(file_handle)
            return args[0]

        file_sender = FileSender()
        reader = HashBlobReader(write_func)
        file_handle = self.open_for_reading()
        if file_handle is not None:
            d = file_sender.beginFileTransfer(file_handle, reader)
            d.addCallback(close_self)
        else:
            d = defer.fail(ValueError("Could not read the blob"))
        return d

    def writer_finished(self, writer, err=None):

        def fire_finished_deferred():
            self._verified = True
            for p, (w, finished_deferred) in self.writers.items():
                if w == writer:
                    finished_deferred.callback(self)
                    del self.writers[p]
                    return True
            log.warning(
                "Somehow, the writer that was accepted as being valid was already removed: %s",
                writer)
            return False

        def errback_finished_deferred(err):
            for p, (w, finished_deferred) in self.writers.items():
                if w == writer:
                    finished_deferred.errback(err)
                    del self.writers[p]

        def cancel_other_downloads():
            for p, (w, finished_deferred) in self.writers.items():
                w.cancel()

        if err is None:
            if writer.len_so_far == self.length and writer.blob_hash == self.blob_hash:
                if self._verified is False:
                    d = self._save_verified_blob(writer)
                    d.addCallbacks(lambda _: fire_finished_deferred(), errback_finished_deferred)
                    d.addCallback(lambda _: cancel_other_downloads())
                else:
                    errback_finished_deferred(Failure(DownloadCanceledError()))
                    d = defer.succeed(True)
            else:
                err_string = "length vs expected: {0}, {1}, hash vs expected: {2}, {3}"
                err_string = err_string.format(self.length, writer.len_so_far, self.blob_hash,
                                               writer.blob_hash)
                errback_finished_deferred(Failure(InvalidDataError(err_string)))
                d = defer.succeed(True)
        else:
            errback_finished_deferred(err)
            d = defer.succeed(True)

        d.addBoth(lambda _: self._close_writer(writer))
        return d

    def open_for_writing(self, peer):
        raise NotImplementedError()

    def open_for_reading(self):
        raise NotImplementedError()

    def delete(self):
        raise NotImplementedError()

    def close_read_handle(self, file_handle):
        raise NotImplementedError()

    def _close_writer(self, writer):
        raise NotImplementedError()

    def _save_verified_blob(self, writer):
        raise NotImplementedError()

    def __str__(self):
        return self.blob_hash[:16]

    def __repr__(self):
        return '<{}({})>'.format(self.__class__.__name__, str(self))


class BlobFile(HashBlob):
    """A HashBlob which will be saved to the hard disk of the downloader"""

    def __init__(self, blob_dir, blob_hash, length=None):
        HashBlob.__init__(self, blob_hash, length)
        self.blob_dir = blob_dir
        self.file_path = os.path.join(blob_dir, self.blob_hash)
        self.setting_verified_blob_lock = threading.Lock()
        self.moved_verified_blob = False
        self.buffer = BytesIO()
        if os.path.isfile(self.file_path):
            self.set_length(os.path.getsize(self.file_path))
            # This assumes that the hash of the blob has already been
            # checked as part of the blob creation process. It might
            # be worth having a function that checks the actual hash;
            # its probably too expensive to have that check be part of
            # this call.
            self._verified = True

    def open_for_writing(self, peer):
        if not peer in self.writers:
            log.debug("Opening %s to be written by %s", str(self), str(peer))
            finished_deferred = defer.Deferred()
            writer = HashBlobWriter(self.buffer, self.get_length, self.writer_finished)
            self.writers[peer] = (writer, finished_deferred)
            return finished_deferred, writer.write, writer.cancel
        log.warning("Tried to download the same file twice simultaneously from the same peer")
        return None, None, None

    def open_for_reading(self):
        if self._verified is True:
            file_handle = None
            try:
                file_handle = open(self.file_path, 'rb')
                self.readers += 1
                return file_handle
            except IOError:
                log.exception('Failed to open %s', self.file_path)
                self.close_read_handle(file_handle)
        return None

    def delete(self):
        if not self.writers and not self.readers:
            self._verified = False
            self.moved_verified_blob = False

            def delete_from_file_system():
                if os.path.isfile(self.file_path):
                    os.remove(self.file_path)

            d = threads.deferToThread(delete_from_file_system)

            def log_error(err):
                log.warning("An error occurred deleting %s: %s",
                            str(self.file_path), err.getErrorMessage())
                return err

            d.addErrback(log_error)
            return d
        else:
            return defer.fail(Failure(
                ValueError("File is currently being read or written and cannot be deleted")))

    def close_read_handle(self, file_handle):
        if file_handle is not None:
            file_handle.close()
            self.readers -= 1

    def _close_writer(self, writer):
        if writer.write_handle is not None:
            log.debug("Closing %s", str(self))
            writer.write_handle.close()
            writer.write_handle = None

    @defer.inlineCallbacks
    def _save_verified_blob(self, writer):
        with self.setting_verified_blob_lock:
            if self.moved_verified_blob is False:
                self.buffer.seek(0)
                out_path = os.path.join(self.blob_dir, self.blob_hash)
                producer = FileBodyProducer(self.buffer)
                yield producer.startProducing(open(out_path, 'wb'))
                self.moved_verified_blob = True
                defer.returnValue(True)
            else:
                raise DownloadCanceledError()


class BlobFileCreator(object):
    def __init__(self, blob_dir):
        self.blob_dir = blob_dir
        self.buffer = BytesIO()
        self._is_open = True
        self._hashsum = get_lbry_hash_obj()
        self.len_so_far = 0
        self.blob_hash = None
        self.length = None

    @defer.inlineCallbacks
    def close(self):
        self.length = self.len_so_far
        self.blob_hash = self._hashsum.hexdigest()
        if self.blob_hash and self._is_open:
            self.buffer.seek(0)
            out_path = os.path.join(self.blob_dir, self.blob_hash)
            producer = FileBodyProducer(self.buffer)
            yield producer.startProducing(open(out_path, 'wb'))
            self._is_open = False
        defer.returnValue(self.blob_hash)

    def write(self, data):
        if not self._is_open:
            raise IOError
        self._hashsum.update(data)
        self.len_so_far += len(data)
        self.buffer.write(data)
