from copy import deepcopy

from lbryschema.schema.schema import Schema
from lbryschema.proto import fee_pb2 as fee_pb
from lbryschema.schema import VERSION_MAP, CURRENCY_MAP


class Fee(Schema):
    @classmethod
    def load(cls, message):
        _fee = deepcopy(message)
        currency = CURRENCY_MAP[_fee.pop('currency')]
        _message_pb = fee_pb.Fee()
        _message_pb.version = VERSION_MAP[_fee.pop("version")]
        _message_pb.currency = currency
        _message_pb.address = _fee.pop('address')
        return cls._load(_fee, _message_pb)
