"""
Utilities for turning plain files into LBRY Files.
"""

import binascii
import logging
import os
from twisted.internet import defer
from lbrynet.core.StreamDescriptor import PlainStreamDescriptorWriter
from lbrynet.cryptstream.CryptStreamCreator import CryptStreamCreator
from lbrynet import conf
from lbrynet.lbryfile.StreamDescriptor import get_sd_info
from lbrynet.core.cryptoutils import get_lbry_hash_obj
from twisted.protocols.basic import FileSender


log = logging.getLogger(__name__)


class EncryptedFileStreamCreator(CryptStreamCreator):
    """
    A CryptStreamCreator which adds itself and its additional metadata to an EncryptedFileManager
    """
    def __init__(self, blob_manager, lbry_file_manager, name=None,
                 key=None, iv_generator=None, suggested_file_name=None):
        CryptStreamCreator.__init__(self, blob_manager, name, key, iv_generator)
        self.lbry_file_manager = lbry_file_manager
        self.suggested_file_name = suggested_file_name or name
        self.stream_hash = None
        self.blob_infos = []

    def _blob_finished(self, blob_info):
        log.debug("length: %s", str(blob_info.length))
        self.blob_infos.append(blob_info)

    def _save_stream_info(self):
        stream_info_manager = self.lbry_file_manager.stream_info_manager
        d = stream_info_manager.save_stream(self.stream_hash, hexlify(self.name),
                                            hexlify(self.key),
                                            hexlify(self.suggested_file_name),
                                            self.blob_infos)
        return d

    def setup(self):
        d = CryptStreamCreator.setup(self)
        return d

    def _get_blobs_hashsum(self):
        blobs_hashsum = get_lbry_hash_obj()
        for blob_info in sorted(self.blob_infos, key=lambda b_i: b_i.blob_num):
            length = blob_info.length
            if length != 0:
                blob_hash = blob_info.blob_hash
            else:
                blob_hash = None
            blob_num = blob_info.blob_num
            iv = blob_info.iv
            blob_hashsum = get_lbry_hash_obj()
            if length != 0:
                blob_hashsum.update(blob_hash)
            blob_hashsum.update(str(blob_num))
            blob_hashsum.update(iv)
            blob_hashsum.update(str(length))
            blobs_hashsum.update(blob_hashsum.digest())
        return blobs_hashsum.digest()

    def _make_stream_hash(self):
        hashsum = get_lbry_hash_obj()
        hashsum.update(hexlify(self.name))
        hashsum.update(hexlify(self.key))
        hashsum.update(hexlify(self.suggested_file_name))
        hashsum.update(self._get_blobs_hashsum())
        self.stream_hash = hashsum.hexdigest()

    def _finished(self):
        self._make_stream_hash()
        d = self._save_stream_info()
        return d


# TODO: this should be run its own thread. Encrypting a large file can
#       be very cpu intensive and there is no need to run that on the
#       main reactor thread. The FileSender mechanism that is used is
#       great when sending over the network, but this is all local so
#       we can simply read the file from the disk without needing to
#       involve reactor.
def create_lbry_file(session, lbry_file_manager, file_name, file_handle, key=None,
                     iv_generator=None, suggested_file_name=None):
    """Turn a plain file into an LBRY File.

    An LBRY File is a collection of encrypted blobs of data and the metadata that binds them
    together which, when decrypted and put back together according to the metadata, results
    in the original file.

    The stream parameters that aren't specified are generated, the file is read and broken
    into chunks and encrypted, and then a stream descriptor file with the stream parameters
    and other metadata is written to disk.

    @param session: An Session object.
    @type session: Session

    @param lbry_file_manager: The EncryptedFileManager object this LBRY File will be added to.
    @type lbry_file_manager: EncryptedFileManager

    @param file_name: The path to the plain file.
    @type file_name: string

    @param file_handle: The file-like object to read
    @type file_handle: any file-like object which can be read by twisted.protocols.basic.FileSender

    @param secret_pass_phrase: A string that will be used to generate the public key. If None, a
        random string will be used.
    @type secret_pass_phrase: string

    @param key: the raw AES key which will be used to encrypt the blobs. If None, a random key will
        be generated.
    @type key: string

    @param iv_generator: a generator which yields initialization
        vectors for the blobs. Will be called once for each blob.
    @type iv_generator: a generator function which yields strings

    @param suggested_file_name: what the file should be called when the LBRY File is saved to disk.
    @type suggested_file_name: string

    @return: a Deferred which fires with the stream_hash of the LBRY File
    @rtype: Deferred which fires with hex-encoded string
    """

    def stop_file(creator):
        log.debug("the file sender has triggered its deferred. stopping the stream writer")
        return creator.stop()

    @defer.inlineCallbacks
    def make_stream_desc_file(stream_hash):
        log.debug("creating the stream descriptor file")
        descriptor_file_path = os.path.join(
            session.db_dir, file_name + conf.settings['CRYPTSD_FILE_EXTENSION'])
        descriptor_writer = PlainStreamDescriptorWriter(descriptor_file_path)

        sd_info = yield get_sd_info(lbry_file_manager.stream_info_manager, stream_hash, True)
        yield descriptor_writer.create_descriptor(sd_info)

    base_file_name = os.path.basename(file_name)

    lbry_file_creator = EncryptedFileStreamCreator(
        session.blob_manager,
        lbry_file_manager,
        base_file_name, key,
        iv_generator,
        suggested_file_name)

    def start_stream():
        # TODO: Using FileSender isn't necessary, we can just read
        #       straight from the disk. The stream creation process
        #       should be in its own thread anyway so we don't need to
        #       worry about interacting with the twisted reactor
        file_sender = FileSender()
        d = file_sender.beginFileTransfer(file_handle, lbry_file_creator)
        d.addCallback(lambda _: stop_file(lbry_file_creator))
        d.addCallback(lambda _: make_stream_desc_file(lbry_file_creator.stream_hash))
        d.addCallback(lambda _: lbry_file_creator.stream_hash)
        return d

    d = lbry_file_creator.setup()
    d.addCallback(lambda _: start_stream())
    return d


def hexlify(str_or_unicode):
    if isinstance(str_or_unicode, unicode):
        strng = str_or_unicode.encode('utf-8')
    else:
        strng = str_or_unicode
    return binascii.hexlify(strng)
