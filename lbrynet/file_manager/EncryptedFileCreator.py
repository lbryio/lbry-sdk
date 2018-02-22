"""
Utilities for turning plain files into LBRY Files.
"""

import binascii
import logging
import os

from twisted.internet import defer
from twisted.protocols.basic import FileSender

from lbrynet.core.StreamDescriptor import BlobStreamDescriptorWriter, EncryptedFileStreamType
from lbrynet.core.StreamDescriptor import format_sd_info, get_stream_hash, validate_descriptor
from lbrynet.cryptstream.CryptStreamCreator import CryptStreamCreator

log = logging.getLogger(__name__)


class EncryptedFileStreamCreator(CryptStreamCreator):
    """
    A CryptStreamCreator which adds itself and its additional metadata to an EncryptedFileManager
    """

    def __init__(self, blob_manager, lbry_file_manager, stream_name=None,
                 key=None, iv_generator=None):
        CryptStreamCreator.__init__(self, blob_manager, stream_name, key, iv_generator)
        self.lbry_file_manager = lbry_file_manager
        self.stream_hash = None
        self.blob_infos = []
        self.sd_info = None

    def _blob_finished(self, blob_info):
        log.debug("length: %s", blob_info.length)
        self.blob_infos.append(blob_info.get_dict())
        return blob_info

    def _finished(self):
        # calculate the stream hash
        self.stream_hash = get_stream_hash(
            hexlify(self.name), hexlify(self.key), hexlify(self.name),
            self.blob_infos
        )

        # generate the sd info
        self.sd_info = format_sd_info(
            EncryptedFileStreamType, hexlify(self.name), hexlify(self.key),
            hexlify(self.name), self.stream_hash, self.blob_infos
        )

        # sanity check
        validate_descriptor(self.sd_info)
        return defer.succeed(self.stream_hash)


# TODO: this should be run its own thread. Encrypting a large file can
#       be very cpu intensive and there is no need to run that on the
#       main reactor thread. The FileSender mechanism that is used is
#       great when sending over the network, but this is all local so
#       we can simply read the file from the disk without needing to
#       involve reactor.
@defer.inlineCallbacks
def create_lbry_file(session, lbry_file_manager, file_name, file_handle, key=None, iv_generator=None):
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

    @param key: the raw AES key which will be used to encrypt the blobs. If None, a random key will
        be generated.
    @type key: string

    @param iv_generator: a generator which yields initialization
        vectors for the blobs. Will be called once for each blob.
    @type iv_generator: a generator function which yields strings

    @return: a Deferred which fires with the stream_hash of the LBRY File
    @rtype: Deferred which fires with hex-encoded string
    """

    base_file_name = os.path.basename(file_name)
    file_directory = os.path.dirname(file_handle.name)

    lbry_file_creator = EncryptedFileStreamCreator(
        session.blob_manager, lbry_file_manager, base_file_name, key, iv_generator
    )

    yield lbry_file_creator.setup()
    # TODO: Using FileSender isn't necessary, we can just read
    #       straight from the disk. The stream creation process
    #       should be in its own thread anyway so we don't need to
    #       worry about interacting with the twisted reactor
    file_sender = FileSender()
    yield file_sender.beginFileTransfer(file_handle, lbry_file_creator)

    log.debug("the file sender has triggered its deferred. stopping the stream writer")
    yield lbry_file_creator.stop()

    log.debug("making the sd blob")
    sd_info = lbry_file_creator.sd_info
    descriptor_writer = BlobStreamDescriptorWriter(session.blob_manager)
    sd_hash = yield descriptor_writer.create_descriptor(sd_info)

    log.debug("saving the stream")
    yield session.storage.store_stream(
        sd_info['stream_hash'], sd_hash, sd_info['stream_name'], sd_info['key'],
        sd_info['suggested_file_name'], sd_info['blobs']
    )
    log.debug("adding to the file manager")
    lbry_file = yield lbry_file_manager.add_published_file(
        sd_info['stream_hash'], sd_hash, binascii.hexlify(file_directory), session.payment_rate_manager,
        session.payment_rate_manager.min_blob_data_payment_rate
    )
    defer.returnValue(lbry_file)


def hexlify(str_or_unicode):
    if isinstance(str_or_unicode, unicode):
        strng = str_or_unicode.encode('utf-8')
    else:
        strng = str_or_unicode
    return binascii.hexlify(strng)
