from copy import deepcopy
from lbryschema.proto import metadata_pb2 as metadata_pb
from lbryschema.schema.fee import Fee
from lbryschema.schema.schema import Schema
from lbryschema.schema import VERSION_MAP


class Metadata(Schema):
    @classmethod
    def load(cls, message):
        _metadata = deepcopy(message)
        _message_pb = metadata_pb.Metadata()
        _message_pb.version = VERSION_MAP[_metadata.pop("version")]
        if 'fee' in _metadata:
            fee_pb = Fee.load(_metadata.pop('fee'))
            _message_pb.fee.CopyFrom(fee_pb)
        return cls._load(_metadata, _message_pb)
