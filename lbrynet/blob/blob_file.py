import logging
import os
import threading
from twisted.internet import defer, threads
from twisted.protocols.basic import FileSender
from twisted.web.client import FileBodyProducer
from twisted.python.failure import Failure
from lbrynet import conf
from lbrynet.core.Error import DownloadCanceledError, InvalidDataError, InvalidBlobHashError
from lbrynet.core.utils import is_valid_blobhash
from lbrynet.blob.writer import HashBlobWriter
from lbrynet.blob.reader import HashBlobReader


log = logging.getLogger(__name__)


class BlobFile(object):
    """
    A chunk of data available on the network which is specified by a hashsum

    This class is used to create blobs on the local filesystem
    when we already know the blob hash before hand (i.e., when downloading blobs)
    Also can be used for reading from blobs on the local filesystem
    """

    def __str__(self):
        return self.blob_hash[:16]

    def __repr__(self):
        return '<{}({})>'.format(self.__class__.__name__, str(self))

    def __init__(self, blob_dir, blob_hash, length=None):
        if not is_valid_blobhash(blob_hash):
            raise InvalidBlobHashError(blob_hash)
        self.blob_hash = blob_hash
        self.length = length
        self.writers = {}  # {Peer: writer, finished_deferred}
        self._verified = False
        self.readers = 0
        self.blob_dir = blob_dir
        self.file_path = os.path.join(blob_dir, self.blob_hash)
        self.setting_verified_blob_lock = threading.Lock()
        self.moved_verified_blob = False
        if os.path.isfile(self.file_path):
            self.set_length(os.path.getsize(self.file_path))
            # This assumes that the hash of the blob has already been
            # checked as part of the blob creation process. It might
            # be worth having a function that checks the actual hash;
            # its probably too expensive to have that check be part of
            # this call.
            self._verified = True

    def open_for_writing(self, peer):
        """
        open a blob file to be written by peer, supports concurrent
        writers, as long as they are from differnt peers.

        returns tuple of (writer, finished_deferred)

        writer - a file like object with a write() function, close() when finished
        finished_deferred - deferred that is fired when write is finished and returns
            a instance of itself as HashBlob
        """
        if not peer in self.writers:
            log.debug("Opening %s to be written by %s", str(self), str(peer))
            finished_deferred = defer.Deferred()
            writer = HashBlobWriter(self.get_length, self.writer_finished)
            self.writers[peer] = (writer, finished_deferred)
            return (writer, finished_deferred)
        log.warning("Tried to download the same file twice simultaneously from the same peer")
        return None, None

    def open_for_reading(self):
        """
        open blob for reading

        returns a file handle that can be read() from.
        once finished with the file handle, user must call close_read_handle()
        otherwise blob cannot be deleted.
        """
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
        """
        delete blob file from file system, prevent deletion
        if a blob is being read from or written to

        returns a deferred that firesback when delete is completed
        """
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

    @property
    def verified(self):
        """
        Protect verified from being modified by other classes.
        verified is True if a write to a blob has completed succesfully,
        or a blob has been read to have the same length as specified
        in init
        """
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

    def get_is_verified(self):
        return self.verified

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
            d = defer.fail(IOError("Could not read the blob"))
        return d

    def writer_finished(self, writer, err=None):
        def fire_finished_deferred():
            self._verified = True
            for p, (w, finished_deferred) in self.writers.items():
                if w == writer:
                    del self.writers[p]
                    finished_deferred.callback(self)
                    return True
            log.warning(
                "Somehow, the writer that was accepted as being valid was already removed: %s",
                writer)
            return False

        def errback_finished_deferred(err):
            for p, (w, finished_deferred) in self.writers.items():
                if w == writer:
                    del self.writers[p]
                    finished_deferred.errback(err)

        def cancel_other_downloads():
            for p, (w, finished_deferred) in self.writers.items():
                w.close()

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
        d.addBoth(lambda _: writer.close_handle())
        return d

    def close_read_handle(self, file_handle):
        if file_handle is not None:
            file_handle.close()
            self.readers -= 1

    @defer.inlineCallbacks
    def _save_verified_blob(self, writer):
        with self.setting_verified_blob_lock:
            if self.moved_verified_blob is False:
                writer.write_handle.seek(0)
                out_path = os.path.join(self.blob_dir, self.blob_hash)
                producer = FileBodyProducer(writer.write_handle)
                yield producer.startProducing(open(out_path, 'wb'))
                self.moved_verified_blob = True
                defer.returnValue(True)
            else:
                raise DownloadCanceledError()
