from lbrynet.core.StreamDescriptor import BlobStreamDescriptorWriter
from lbrynet.lbrylive.StreamDescriptor import get_sd_info
from lbrynet.cryptstream.CryptStreamCreator import CryptStreamCreator
from lbrynet.lbrylive.LiveBlob import LiveStreamBlobMaker
from lbrynet.core.cryptoutils import get_lbry_hash_obj, get_pub_key, sign_with_pass_phrase
from Crypto import Random
import binascii
import logging
from lbrynet.conf import CRYPTSD_FILE_EXTENSION
from twisted.internet import interfaces, defer
from twisted.protocols.basic import FileSender
from zope.interface import implements


class LiveStreamCreator(CryptStreamCreator):
    def __init__(self, blob_manager, stream_info_manager, name=None, key=None, iv_generator=None,
                 delete_after_num=None, secret_pass_phrase=None):
        CryptStreamCreator.__init__(self, blob_manager, name, key, iv_generator)
        self.stream_hash = None
        self.stream_info_manager = stream_info_manager
        self.delete_after_num = delete_after_num
        self.secret_pass_phrase = secret_pass_phrase
        self.file_extension = CRYPTSD_FILE_EXTENSION
        self.finished_blob_hashes = {}

    def _save_stream(self):
        d = self.stream_info_manager.save_stream(self.stream_hash, get_pub_key(self.secret_pass_phrase),
                                                 binascii.hexlify(self.name), binascii.hexlify(self.key),
                                                 [])
        return d

    def _blob_finished(self, blob_info):
        logging.debug("In blob_finished")
        logging.debug("length: %s", str(blob_info.length))
        sig_hash = get_lbry_hash_obj()
        sig_hash.update(self.stream_hash)
        if blob_info.length != 0:
            sig_hash.update(blob_info.blob_hash)
        sig_hash.update(str(blob_info.blob_num))
        sig_hash.update(str(blob_info.revision))
        sig_hash.update(blob_info.iv)
        sig_hash.update(str(blob_info.length))
        signature = sign_with_pass_phrase(sig_hash.digest(), self.secret_pass_phrase)
        blob_info.signature = signature
        self.finished_blob_hashes[blob_info.blob_num] = blob_info.blob_hash
        if self.delete_after_num is not None:
            self._delete_old_blobs(blob_info.blob_num)
        d = self.stream_info_manager.add_blobs_to_stream(self.stream_hash, [blob_info])

        def log_add_error(err):
            logging.error("An error occurred adding a blob info to the stream info manager: %s", err.getErrorMessage())
            return err

        d.addErrback(log_add_error)
        logging.debug("returning from blob_finished")
        return d

    def setup(self):
        """Create the secret pass phrase if it wasn't provided, compute the stream hash,
        save the stream to the stream info manager, and return the stream hash
        """
        if self.secret_pass_phrase is None:
            self.secret_pass_phrase = Random.new().read(512)

        d = CryptStreamCreator.setup(self)

        def make_stream_hash():
            hashsum = get_lbry_hash_obj()
            hashsum.update(binascii.hexlify(self.name))
            hashsum.update(get_pub_key(self.secret_pass_phrase))
            hashsum.update(binascii.hexlify(self.key))
            self.stream_hash = hashsum.hexdigest()
            return self.stream_hash

        d.addCallback(lambda _: make_stream_hash())
        d.addCallback(lambda _: self._save_stream())
        d.addCallback(lambda _: self.stream_hash)
        return d

    def publish_stream_descriptor(self):
        descriptor_writer = BlobStreamDescriptorWriter(self.blob_manager)
        d = get_sd_info(self.stream_info_manager, self.stream_hash, False)
        d.addCallback(descriptor_writer.create_descriptor)
        return d

    def _delete_old_blobs(self, newest_blob_num):
        assert self.delete_after_num is not None, "_delete_old_blobs called with delete_after_num=None"
        oldest_to_keep = newest_blob_num - self.delete_after_num + 1
        nums_to_delete = [num for num in self.finished_blob_hashes.iterkeys() if num < oldest_to_keep]
        for num in nums_to_delete:
            self.blob_manager.delete_blobs([self.finished_blob_hashes[num]])
            del self.finished_blob_hashes[num]

    def _get_blob_maker(self, iv, blob_creator):
        return LiveStreamBlobMaker(self.key, iv, self.blob_count, blob_creator)


class StdOutLiveStreamCreator(LiveStreamCreator):
    def __init__(self, stream_name, blob_manager, stream_info_manager):
        LiveStreamCreator.__init__(self, blob_manager, stream_info_manager, stream_name,
                                   delete_after_num=20)

    def start_streaming(self):
        stdin_producer = StdinStreamProducer(self)
        d = stdin_producer.begin_producing()

        def stop_stream():
            d = self.stop()
            return d

        d.addCallback(lambda _: stop_stream())
        return d


class FileLiveStreamCreator(LiveStreamCreator):
    def __init__(self, blob_manager, stream_info_manager, file_name, file_handle,
                 secret_pass_phrase=None, key=None, iv_generator=None, stream_name=None):
        if stream_name is None:
            stream_name = file_name
        LiveStreamCreator.__init__(self, blob_manager, stream_info_manager, stream_name,
                                   secret_pass_phrase, key, iv_generator)
        self.file_name = file_name
        self.file_handle = file_handle

    def start_streaming(self):
        file_sender = FileSender()
        d = file_sender.beginFileTransfer(self.file_handle, self)

        def stop_stream():
            d = self.stop()
            return d

        d.addCallback(lambda _: stop_stream())
        return d


class StdinStreamProducer(object):
    """This class reads data from standard in and sends it to a stream creator"""

    implements(interfaces.IPushProducer)

    def __init__(self, consumer):
        self.consumer = consumer
        self.reader = None
        self.finished_deferred = None

    def begin_producing(self):

        self.finished_deferred = defer.Deferred()
        self.consumer.registerProducer(self, True)
        #self.reader = process.ProcessReader(reactor, self, 'read', 0)
        self.resumeProducing()
        return self.finished_deferred

    def resumeProducing(self):
        if self.reader is not None:
            self.reader.resumeProducing()

    def stopProducing(self):
        if self.reader is not None:
            self.reader.stopReading()
        self.consumer.unregisterProducer()
        self.finished_deferred.callback(True)

    def pauseProducing(self):
        if self.reader is not None:
            self.reader.pauseProducing()

    def childDataReceived(self, fd, data):
        self.consumer.write(data)

    def childConnectionLost(self, fd, reason):
        self.stopProducing()