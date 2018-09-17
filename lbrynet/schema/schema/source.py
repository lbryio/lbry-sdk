from copy import deepcopy
from lbryschema.proto import source_pb2 as source_pb
from lbryschema.schema import SOURCE_TYPES, LBRY_SD_HASH_LENGTH, VERSION_MAP
from lbryschema.schema.schema import Schema
from lbryschema.error import InvalidSourceHashLength


class Source(Schema):
    @classmethod
    def load(cls, message):
        _source = deepcopy(message)
        sd_hash = _source.pop('source')
        assert len(sd_hash) == LBRY_SD_HASH_LENGTH, InvalidSourceHashLength(len(sd_hash))
        _message_pb = source_pb.Source()
        _message_pb.version = VERSION_MAP[_source.pop("version")]
        _message_pb.sourceType = SOURCE_TYPES[_source.pop('sourceType')]
        _message_pb.source = sd_hash
        _message_pb.contentType = _source.pop('contentType')
        return cls._load(_source, _message_pb)
