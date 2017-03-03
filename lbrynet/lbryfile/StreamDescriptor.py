import binascii
import logging
from lbrynet.core.cryptoutils import get_lbry_hash_obj
from lbrynet.cryptstream.CryptBlob import CryptBlobInfo
from twisted.internet import defer, threads
from lbrynet.core.Error import DuplicateStreamHashError, InvalidStreamDescriptorError
from lbrynet.core.StreamDescriptor import PlainStreamDescriptorWriter, BlobStreamDescriptorWriter
import os

log = logging.getLogger(__name__)
EncryptedFileStreamType = "lbryfile"


def save_sd_info(stream_info_manager, sd_info, ignore_duplicate=False):
    log.info("Saving info for %s", str(sd_info['stream_name']))
    hex_stream_name = sd_info['stream_name']
    key = sd_info['key']
    stream_hash = sd_info['stream_hash']
    raw_blobs = sd_info['blobs']
    suggested_file_name = sd_info['suggested_file_name']
    crypt_blobs = []
    for blob in raw_blobs:
        length = blob['length']
        if length != 0:
            blob_hash = blob['blob_hash']
        else:
            blob_hash = None
        blob_num = blob['blob_num']
        iv = blob['iv']
        crypt_blobs.append(CryptBlobInfo(blob_hash, blob_num, length, iv))
    log.info("Trying to save stream info for %s (%i blobs)", str(hex_stream_name), len(crypt_blobs))
    d = stream_info_manager.save_stream(stream_hash, hex_stream_name, key,
                                        suggested_file_name, crypt_blobs)

    def check_if_duplicate(err):
        if ignore_duplicate is True:
            err.trap(DuplicateStreamHashError)

    d.addErrback(check_if_duplicate)
    d.addCallback(lambda _: stream_hash)
    return d


@defer.inlineCallbacks
def get_sd_info(stream_info_manager, stream_hash, include_blobs):
    stream_info = yield stream_info_manager.get_stream_info(stream_hash)
    log.info("Stream info: %s", stream_info)
    fields = {}
    fields['stream_type'] = EncryptedFileStreamType
    fields['key'], fields['stream_name'], fields['suggested_file_name'] = stream_info
    fields['stream_hash'] = stream_hash
    if include_blobs is True:
        blobs = yield stream_info_manager.get_blobs_for_stream(stream_hash)
    else:
        blobs = []
    formatted_blobs = []
    for blob_hash, blob_num, iv, length in blobs:
        blob = {}
        if blob_hash is not None:
            blob['blob_hash'] = blob_hash
        blob['blob_num'] = blob_num
        blob['iv'] = iv
        blob['length'] = length
        formatted_blobs.append(blob)
    fields['blobs'] = formatted_blobs
    defer.returnValue(fields)


@defer.inlineCallbacks
def publish_sd_blob(stream_info_manager, blob_manager, stream_hash):
    descriptor_writer = BlobStreamDescriptorWriter(blob_manager)
    sd_info = yield get_sd_info(stream_info_manager, stream_hash, True)
    sd_blob_hash = yield descriptor_writer.create_descriptor(sd_info)
    yield stream_info_manager.save_sd_blob_hash_to_stream(stream_hash, sd_blob_hash)
    defer.returnValue(sd_blob_hash)


def create_plain_sd(stream_info_manager, stream_hash, file_name, overwrite_existing=False):

    def _get_file_name():
        actual_file_name = file_name
        if os.path.exists(actual_file_name):
            ext_num = 1
            while os.path.exists(actual_file_name + "_" + str(ext_num)):
                ext_num += 1
            actual_file_name = actual_file_name + "_" + str(ext_num)
        return actual_file_name

    if overwrite_existing is False:
        d = threads.deferToThread(_get_file_name())
    else:
        d = defer.succeed(file_name)

    def do_create(file_name):
        descriptor_writer = PlainStreamDescriptorWriter(file_name)
        d = get_sd_info(stream_info_manager, stream_hash, True)
        d.addCallback(descriptor_writer.create_descriptor)
        return d

    d.addCallback(do_create)
    return d


class EncryptedFileStreamDescriptorValidator(object):
    def __init__(self, raw_info):
        self.raw_info = raw_info

    def validate(self):
        log.debug("Trying to validate stream descriptor for %s", str(self.raw_info['stream_name']))
        try:
            hex_stream_name = self.raw_info['stream_name']
            key = self.raw_info['key']
            hex_suggested_file_name = self.raw_info['suggested_file_name']
            stream_hash = self.raw_info['stream_hash']
            blobs = self.raw_info['blobs']
        except KeyError as e:
            raise InvalidStreamDescriptorError("Missing '%s'" % (e.args[0]))
        for c in hex_suggested_file_name:
            if c not in '0123456789abcdef':
                raise InvalidStreamDescriptorError(
                    "Suggested file name is not a hex-encoded string")
        h = get_lbry_hash_obj()
        h.update(hex_stream_name)
        h.update(key)
        h.update(hex_suggested_file_name)

        def get_blob_hashsum(b):
            length = b['length']
            if length != 0:
                blob_hash = b.get('blob_hash', None)
            else:
                blob_hash = None
            blob_num = b['blob_num']
            iv = b['iv']
            blob_hashsum = get_lbry_hash_obj()
            if blob_hash is not None:
                blob_hashsum.update(blob_hash)
            blob_hashsum.update(str(blob_num))
            blob_hashsum.update(iv)
            blob_hashsum.update(str(length))
            return blob_hashsum.digest()

        blobs_hashsum = get_lbry_hash_obj()
        for blob in blobs:
            blobs_hashsum.update(get_blob_hashsum(blob))
        if blobs[-1]['length'] != 0:
            raise InvalidStreamDescriptorError("Does not end with a zero-length blob.")
        h.update(blobs_hashsum.digest())
        if h.hexdigest() != stream_hash:
            raise InvalidStreamDescriptorError("Stream hash does not match stream metadata")
        log.debug("It is validated")
        return defer.succeed(True)

    def info_to_show(self):
        info = []
        info.append(("stream_name", binascii.unhexlify(self.raw_info.get("stream_name"))))
        size_so_far = 0
        for blob_info in self.raw_info.get("blobs", []):
            size_so_far += int(blob_info['length'])
        info.append(("stream_size", str(self.get_length_of_stream())))
        suggested_file_name = self.raw_info.get("suggested_file_name", None)
        if suggested_file_name is not None:
            suggested_file_name = binascii.unhexlify(suggested_file_name)
        info.append(("suggested_file_name", suggested_file_name))
        return info

    def get_length_of_stream(self):
        size_so_far = 0
        for blob_info in self.raw_info.get("blobs", []):
            size_so_far += int(blob_info['length'])
        return size_so_far
