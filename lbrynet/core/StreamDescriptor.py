import os
import binascii
from collections import defaultdict
import json
import logging

from twisted.internet import threads, defer
from lbrynet.core.cryptoutils import get_lbry_hash_obj
from lbrynet.core.client.StandaloneBlobDownloader import StandaloneBlobDownloader
from lbrynet.core.Error import UnknownStreamTypeError, InvalidStreamDescriptorError


log = logging.getLogger(__name__)


class StreamDescriptorReader(object):
    """Classes which derive from this class read a stream descriptor file return
       a dictionary containing the fields in the file"""
    def __init__(self):
        pass

    def _get_raw_data(self):
        """This method must be overridden by subclasses. It should return a deferred
           which fires with the raw data in the stream descriptor"""
        pass

    def get_info(self):
        """Return the fields contained in the file"""
        d = self._get_raw_data()
        d.addCallback(json.loads)
        return d


class PlainStreamDescriptorReader(StreamDescriptorReader):
    """Read a stream descriptor file which is not a blob but a regular file"""
    def __init__(self, stream_descriptor_filename):
        StreamDescriptorReader.__init__(self)
        self.stream_descriptor_filename = stream_descriptor_filename

    def _get_raw_data(self):

        def get_data():
            with open(self.stream_descriptor_filename) as file_handle:
                raw_data = file_handle.read()
                return raw_data

        return threads.deferToThread(get_data)


class BlobStreamDescriptorReader(StreamDescriptorReader):
    """Read a stream descriptor file which is a blob"""
    def __init__(self, blob):
        StreamDescriptorReader.__init__(self)
        self.blob = blob

    def _get_raw_data(self):

        def get_data():
            f = self.blob.open_for_reading()
            if f is not None:
                raw_data = f.read()
                f.close()
                return raw_data
            else:
                raise ValueError("Could not open the blob for reading")

        return threads.deferToThread(get_data)


class StreamDescriptorWriter(object):
    """Classes which derive from this class write fields from a dictionary
       of fields to a stream descriptor"""
    def __init__(self):
        pass

    def create_descriptor(self, sd_info):
        return self._write_stream_descriptor(json.dumps(sd_info))

    def _write_stream_descriptor(self, raw_data):
        """This method must be overridden by subclasses to write raw data to
        the stream descriptor
        """
        pass


class PlainStreamDescriptorWriter(StreamDescriptorWriter):
    def __init__(self, sd_file_name):
        StreamDescriptorWriter.__init__(self)
        self.sd_file_name = sd_file_name

    def _write_stream_descriptor(self, raw_data):

        def write_file():
            log.info("Writing the sd file to disk")
            with open(self.sd_file_name, 'w') as sd_file:
                sd_file.write(raw_data)
            return self.sd_file_name

        return threads.deferToThread(write_file)


class BlobStreamDescriptorWriter(StreamDescriptorWriter):
    def __init__(self, blob_manager):
        StreamDescriptorWriter.__init__(self)
        self.blob_manager = blob_manager

    @defer.inlineCallbacks
    def _write_stream_descriptor(self, raw_data):
        log.debug("Creating the new blob for the stream descriptor")
        blob_creator = self.blob_manager.get_blob_creator()
        blob_creator.write(raw_data)
        log.debug("Wrote the data to the new blob")
        sd_hash = yield blob_creator.close()
        yield self.blob_manager.creator_finished(blob_creator, should_announce=True)
        defer.returnValue(sd_hash)


class StreamMetadata(object):
    FROM_BLOB = 1
    FROM_PLAIN = 2

    def __init__(self, validator, options, factories):
        self.validator = validator
        self.options = options
        self.factories = factories
        self.metadata_source = None
        self.source_blob_hash = None
        self.source_file = None


class StreamDescriptorIdentifier(object):
    """Tries to determine the type of stream described by the stream descriptor using the
       'stream_type' field. Keeps a list of StreamDescriptorValidators and StreamDownloaderFactorys
       and returns the appropriate ones based on the type of the stream descriptor given
    """
    def __init__(self):
        # {stream_type: IStreamDescriptorValidator}
        self._sd_info_validators = {}
        # {stream_type: IStreamOptions
        self._stream_options = {}
        # {stream_type: [IStreamDownloaderFactory]}
        self._stream_downloader_factories = defaultdict(list)

    def add_stream_type(self, stream_type, sd_info_validator, stream_options):
        """This is how the StreamDescriptorIdentifier learns about new types of stream descriptors.

        There can only be one StreamDescriptorValidator for each type of stream.

        @param stream_type: A string representing the type of stream
            descriptor. This must be unique to this stream descriptor.

        @param sd_info_validator: A class implementing the
            IStreamDescriptorValidator interface. This class's
            constructor will be passed the raw metadata in the stream
            descriptor file and its 'validate' method will then be
            called. If the validation step fails, an exception will be
            thrown, preventing the stream descriptor from being
            further processed.

        @param stream_options: A class implementing the IStreamOptions
            interface. This class's constructor will be passed the
            sd_info_validator object containing the raw metadata from
            the stream descriptor file.

        @return: None

        """
        self._sd_info_validators[stream_type] = sd_info_validator
        self._stream_options[stream_type] = stream_options

    def add_stream_downloader_factory(self, stream_type, factory):
        """Register a stream downloader factory with the StreamDescriptorIdentifier.

        This is how the StreamDescriptorIdentifier determines what
        factories may be used to process different stream descriptor
        files. There must be at least one factory for each type of
        stream added via "add_stream_info_validator".

        @param stream_type: A string representing the type of stream
        descriptor which the factory knows how to process.

        @param factory: An object implementing the IStreamDownloaderFactory interface.

        @return: None

        """
        self._stream_downloader_factories[stream_type].append(factory)

    def _return_metadata(self, options_validator_factories, source_type, source):
        validator, options, factories = options_validator_factories
        m = StreamMetadata(validator, options, factories)
        m.metadata_source = source_type
        if source_type == StreamMetadata.FROM_BLOB:
            m.source_blob_hash = source
        if source_type == StreamMetadata.FROM_PLAIN:
            m.source_file = source
        return m

    def get_metadata_for_sd_file(self, sd_path):
        sd_reader = PlainStreamDescriptorReader(sd_path)
        d = sd_reader.get_info()
        d.addCallback(self._return_options_and_validator_and_factories)
        d.addCallback(self._return_metadata, StreamMetadata.FROM_PLAIN, sd_path)
        return d

    def get_metadata_for_sd_blob(self, sd_blob):
        sd_reader = BlobStreamDescriptorReader(sd_blob)
        d = sd_reader.get_info()
        d.addCallback(self._return_options_and_validator_and_factories)
        d.addCallback(self._return_metadata, StreamMetadata.FROM_BLOB, sd_blob.blob_hash)
        return d

    def _get_factories(self, stream_type):
        if not stream_type in self._stream_downloader_factories:
            raise UnknownStreamTypeError(stream_type)
        return self._stream_downloader_factories[stream_type]

    def _get_validator(self, stream_type):
        if not stream_type in self._sd_info_validators:
            raise UnknownStreamTypeError(stream_type)
        return self._sd_info_validators[stream_type]

    def _get_options(self, stream_type):
        if not stream_type in self._stream_downloader_factories:
            raise UnknownStreamTypeError(stream_type)
        return self._stream_options[stream_type]

    def _return_options_and_validator_and_factories(self, sd_info):
        if not 'stream_type' in sd_info:
            raise InvalidStreamDescriptorError('No stream_type parameter in stream descriptor.')
        stream_type = sd_info['stream_type']
        validator = self._get_validator(stream_type)(sd_info)
        factories = [f for f in self._get_factories(stream_type) if f.can_download(validator)]

        d = validator.validate()

        def get_options():
            options = self._get_options(stream_type)
            return validator, options, factories

        d.addCallback(lambda _: get_options())
        return d


EncryptedFileStreamType = "lbryfile"


@defer.inlineCallbacks
def save_sd_info(blob_manager, sd_hash, sd_info):
    if not blob_manager.blobs.get(sd_hash) or not blob_manager.blobs[sd_hash].get_is_verified():
        descriptor_writer = BlobStreamDescriptorWriter(blob_manager)
        calculated_sd_hash = yield descriptor_writer.create_descriptor(sd_info)
        if calculated_sd_hash != sd_hash:
            raise InvalidStreamDescriptorError("%s does not match calculated %s" %
                                               (sd_hash, calculated_sd_hash))
    stream_hash = yield blob_manager.storage.get_stream_hash_for_sd_hash(sd_hash)
    if not stream_hash:
        log.debug("Saving info for %s", sd_info['stream_name'].decode('hex'))
        stream_name = sd_info['stream_name']
        key = sd_info['key']
        stream_hash = sd_info['stream_hash']
        stream_blobs = sd_info['blobs']
        suggested_file_name = sd_info['suggested_file_name']
        yield blob_manager.storage.add_known_blobs(stream_blobs)
        yield blob_manager.storage.store_stream(
            stream_hash, sd_hash, stream_name, key, suggested_file_name, stream_blobs
        )
    defer.returnValue(stream_hash)


def format_blobs(crypt_blob_infos):
    formatted_blobs = []
    for blob_info in crypt_blob_infos:
        blob = {}
        if blob_info.length != 0:
            blob['blob_hash'] = str(blob_info.blob_hash)
        blob['blob_num'] = blob_info.blob_num
        blob['iv'] = str(blob_info.iv)
        blob['length'] = blob_info.length
        formatted_blobs.append(blob)
    return formatted_blobs


def format_sd_info(stream_type, stream_name, key, suggested_file_name, stream_hash, blobs):
    return {
        "stream_type": stream_type,
        "stream_name": stream_name,
        "key": key,
        "suggested_file_name": suggested_file_name,
        "stream_hash": stream_hash,
        "blobs": blobs
    }


@defer.inlineCallbacks
def get_sd_info(storage, stream_hash, include_blobs):
    """
    Get an sd info dictionary from storage

    :param storage: (SQLiteStorage) storage instance
    :param stream_hash: (str) stream hash
    :param include_blobs: (bool) include stream blob infos

    :return: {
        "stream_type": "lbryfile",
        "stream_name": <hex encoded stream name>,
        "key": <stream key>,
        "suggested_file_name": <hex encoded suggested file name>,
        "stream_hash": <stream hash>,
        "blobs": [
            {
                "blob_hash": <head blob_hash>,
                "blob_num": 0,
                "iv": <iv>,
                "length": <head blob length>
            }, ...
            {
                "blob_num": <stream length>,
                "iv": <iv>,
                "length": 0
            }
        ]
    }
    """

    stream_info = yield storage.get_stream_info(stream_hash)
    blobs = []
    if include_blobs:
        blobs = yield storage.get_blobs_for_stream(stream_hash)
    defer.returnValue(
        format_sd_info(
            EncryptedFileStreamType, stream_info[0], stream_info[1],
            stream_info[2], stream_hash, format_blobs(blobs)
        )
    )


def get_blob_hashsum(b):
    length = b['length']
    if length != 0:
        blob_hash = b['blob_hash']
    else:
        blob_hash = None
    blob_num = b['blob_num']
    iv = b['iv']
    blob_hashsum = get_lbry_hash_obj()
    if length != 0:
        blob_hashsum.update(blob_hash)
    blob_hashsum.update(str(blob_num))
    blob_hashsum.update(iv)
    blob_hashsum.update(str(length))
    return blob_hashsum.digest()


def get_stream_hash(hex_stream_name, key, hex_suggested_file_name, blob_infos):
    h = get_lbry_hash_obj()
    h.update(hex_stream_name)
    h.update(key)
    h.update(hex_suggested_file_name)
    blobs_hashsum = get_lbry_hash_obj()
    sorted_blob_infos = sorted(blob_infos, key=lambda x: x['blob_num'])
    for blob in sorted_blob_infos:
        blobs_hashsum.update(get_blob_hashsum(blob))
    if sorted_blob_infos[-1]['length'] != 0:
        raise InvalidStreamDescriptorError("Does not end with a zero-length blob.")
    if 'blob_hash' in sorted_blob_infos[-1]:
        raise InvalidStreamDescriptorError("Stream terminator blob should not have a hash")
    h.update(blobs_hashsum.digest())
    return h.hexdigest()


def verify_hex(text, field_name):
    for c in text:
        if c not in '0123456789abcdef':
            raise InvalidStreamDescriptorError("%s is not a hex-encoded string" % field_name)


def validate_descriptor(stream_info):
    try:
        hex_stream_name = stream_info['stream_name']
        key = stream_info['key']
        hex_suggested_file_name = stream_info['suggested_file_name']
        stream_hash = stream_info['stream_hash']
        blobs = stream_info['blobs']
    except KeyError as e:
        raise InvalidStreamDescriptorError("Missing '%s'" % (e.args[0]))

    verify_hex(key, "key")
    verify_hex(hex_suggested_file_name, "suggested file name")
    verify_hex(stream_hash, "stream_hash")

    calculated_stream_hash = get_stream_hash(
        hex_stream_name, key, hex_suggested_file_name, blobs
    )
    if calculated_stream_hash != stream_hash:
        raise InvalidStreamDescriptorError("Stream hash does not match stream metadata")
    return True


class EncryptedFileStreamDescriptorValidator(object):
    def __init__(self, raw_info):
        self.raw_info = raw_info

    def validate(self):
        return defer.succeed(validate_descriptor(self.raw_info))

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


@defer.inlineCallbacks
def download_sd_blob(session, blob_hash, payment_rate_manager, timeout=None):
    """
    Downloads a single blob from the network

    @param session:

    @param blob_hash:

    @param payment_rate_manager:

    @return: An object of type HashBlob
    """

    downloader = StandaloneBlobDownloader(blob_hash,
                                          session.blob_manager,
                                          session.peer_finder,
                                          session.rate_limiter,
                                          payment_rate_manager,
                                          session.wallet,
                                          timeout)
    sd_blob = yield downloader.download()
    sd_reader = BlobStreamDescriptorReader(sd_blob)
    sd_info = yield sd_reader.get_info()
    raw_sd = yield sd_reader._get_raw_data()
    yield session.blob_manager.storage.add_known_blob(blob_hash, len(raw_sd))
    yield save_sd_info(session.blob_manager, sd_blob.blob_hash, sd_info)
    defer.returnValue(sd_blob)
