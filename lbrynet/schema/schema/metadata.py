from copy import deepcopy
from lbrynet.schema.proto import metadata_pb2 as metadata_pb
from lbrynet.schema.schema.fee import Fee
from lbrynet.schema.schema.schema import Schema
from lbrynet.schema.schema import VERSION_MAP


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
