import binascii
import logging
from lbrynet.core.cryptoutils import get_lbry_hash_obj, verify_signature
from twisted.internet import defer, threads
from lbrynet.core.Error import DuplicateStreamHashError
from lbrynet.lbrylive.LiveBlob import LiveBlobInfo
from lbrynet.interfaces import IStreamDescriptorValidator
from zope.interface import implements


LiveStreamType = "lbrylive"


def save_sd_info(stream_info_manager, sd_info, ignore_duplicate=False):
    logging.debug("Saving info for %s", str(sd_info['stream_name']))
    hex_stream_name = sd_info['stream_name']
    public_key = sd_info['public_key']
    key = sd_info['key']
    stream_hash = sd_info['stream_hash']
    raw_blobs = sd_info['blobs']
    crypt_blobs = []
    for blob in raw_blobs:
        length = blob['length']
        if length != 0:
            blob_hash = blob['blob_hash']
        else:
            blob_hash = None
        blob_num = blob['blob_num']
        revision = blob['revision']
        iv = blob['iv']
        signature = blob['signature']
        crypt_blobs.append(LiveBlobInfo(blob_hash, blob_num, length, iv, revision, signature))
    logging.debug("Trying to save stream info for %s", str(hex_stream_name))
    d = stream_info_manager.save_stream(stream_hash, public_key, hex_stream_name,
                                        key, crypt_blobs)

    def check_if_duplicate(err):
        if ignore_duplicate is True:
            err.trap(DuplicateStreamHashError)

    d.addErrback(check_if_duplicate)

    d.addCallback(lambda _: stream_hash)
    return d


def get_sd_info(stream_info_manager, stream_hash, include_blobs):
    d = stream_info_manager.get_stream_info(stream_hash)

    def format_info(stream_info):
        fields = {}
        fields['stream_type'] = LiveStreamType
        fields['stream_name'] = stream_info[2]
        fields['public_key'] = stream_info[0]
        fields['key'] = stream_info[1]
        fields['stream_hash'] = stream_hash

        def format_blobs(blobs):
            formatted_blobs = []
            for blob_hash, blob_num, revision, iv, length, signature in blobs:
                blob = {}
                if length != 0:
                    blob['blob_hash'] = blob_hash
                blob['blob_num'] = blob_num
                blob['revision'] = revision
                blob['iv'] = iv
                blob['length'] = length
                blob['signature'] = signature
                formatted_blobs.append(blob)
            fields['blobs'] = formatted_blobs
            return fields

        if include_blobs is True:
            d = stream_info_manager.get_blobs_for_stream(stream_hash)
        else:
            d = defer.succeed([])
        d.addCallback(format_blobs)
        return d

    d.addCallback(format_info)
    return d


class LBRYLiveStreamDescriptorValidator(object):
    implements(IStreamDescriptorValidator)

    def __init__(self, raw_info):
        self.raw_info = raw_info

    def validate(self):
        logging.debug("Trying to validate stream descriptor for %s", str(self.raw_info['stream_name']))
        hex_stream_name = self.raw_info['stream_name']
        public_key = self.raw_info['public_key']
        key = self.raw_info['key']
        stream_hash = self.raw_info['stream_hash']
        h = get_lbry_hash_obj()
        h.update(hex_stream_name)
        h.update(public_key)
        h.update(key)
        if h.hexdigest() != stream_hash:
            raise ValueError("Stream hash does not match stream metadata")
        blobs = self.raw_info['blobs']

        def check_blob_signatures():
            for blob in blobs:
                length = blob['length']
                if length != 0:
                    blob_hash = blob['blob_hash']
                else:
                    blob_hash = None
                blob_num = blob['blob_num']
                revision = blob['revision']
                iv = blob['iv']
                signature = blob['signature']
                hashsum = get_lbry_hash_obj()
                hashsum.update(stream_hash)
                if length != 0:
                    hashsum.update(blob_hash)
                hashsum.update(str(blob_num))
                hashsum.update(str(revision))
                hashsum.update(iv)
                hashsum.update(str(length))
                if not verify_signature(hashsum.digest(), signature, public_key):
                    raise ValueError("Invalid signature in stream descriptor")

        return threads.deferToThread(check_blob_signatures)

    def info_to_show(self):
        info = []
        info.append(("stream_name", binascii.unhexlify(self.raw_info.get("stream_name"))))
        return info