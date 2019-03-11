import json
from copy import deepcopy

import google.protobuf.json_format as json_pb  # pylint: disable=no-name-in-module
from google.protobuf.message import Message  # pylint: disable=no-name-in-module,import-error

from lbrynet.schema.proto3 import claim_pb2 as claim_pb
from torba.client.constants import COIN


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
            _message_pb.type = Claim.CLAIM_TYPE_STREAM
            _stream = _claim.pop("stream")
            if "source" in _stream:
                _source = _stream.pop("source")
                _message_pb.stream.hash = _source.get("source", b'')  # fixme: fail if empty?
                _message_pb.stream.media_type = _source.pop("contentType")
            if "metadata" in _stream:
                _metadata = _stream.pop("metadata")
                _message_pb.stream.license = _metadata.get("license")
                _message_pb.stream.description = _metadata.get("description")
                _message_pb.stream.language = _metadata.get("language")
                _message_pb.stream.title = _metadata.get("title")
                _message_pb.stream.author = _metadata.get("author")
                _message_pb.stream.license_url = _metadata.get("licenseUrl")
                _message_pb.stream.thumbnail_url = _metadata.get("thumbnail")
                if _metadata.get("nsfw"):
                    _message_pb.stream.tags.append("nsfw")
                if "fee" in _metadata:
                    _message_pb.stream.fee.address = _metadata["fee"]["address"]
                    _message_pb.stream.fee.currency = {
                        "LBC": 0,
                        "USD": 1
                    }[_metadata["fee"]["currency"]]
                    multiplier = COIN if _metadata["fee"]["currency"] == "LBC" else 100
                    total = int(_metadata["fee"]["amount"]*multiplier)
                    _message_pb.stream.fee.amount = total if total >= 0 else 0
            _claim = {}
        else:
            raise AttributeError

        return cls._load(_claim, _message_pb)
