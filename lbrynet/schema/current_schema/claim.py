import json
from copy import deepcopy

import google.protobuf.json_format as json_pb  # pylint: disable=no-name-in-module
from google.protobuf.message import Message  # pylint: disable=no-name-in-module,import-error

from lbrynet.schema.proto3 import claim_pb2 as claim_pb


class Schema(Message):
    @classmethod
    def load(cls, message):
        raise NotImplementedError

    @classmethod
    def _load(cls, data, message):
        if isinstance(data, dict):
            data = json.dumps(data)
        return json_pb.Parse(data, message)


class Claim(Schema):
    CLAIM_TYPE_STREAM = 0  #fixme: 0 is unset, should be fixed on proto file to be 1 and 2!
    CLAIM_TYPE_CERT = 1

    @classmethod
    def load(cls, message: dict):
        _claim = deepcopy(message)
        _message_pb = claim_pb.Claim()

        if "certificate" in _claim:  # old protobuf, migrate
            _cert = _claim.pop("certificate")
            assert isinstance(_cert, dict)
            _message_pb.type = Claim.CLAIM_TYPE_CERT
            _message_pb.channel.MergeFrom(claim_pb.Channel(public_key=_cert.pop("publicKey")))
            _claim = {}  # so we dont need to know what other fields we ignored
        elif "channel" in _claim:
           _channel = _claim.pop("channel")
           _message_pb.type = Claim.CLAIM_TYPE_CERT
           _message_pb.channel = claim_pb.Channel(**_channel)
        elif "stream" in _claim:
            pass  # fixme
        else:
            raise AttributeError

        return cls._load(_claim, _message_pb)
