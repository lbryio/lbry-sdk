from copy import deepcopy

from lbryschema.proto import certificate_pb2 as cert_pb
from lbryschema.schema.schema import Schema
from lbryschema.schema import VERSION_MAP, V_0_0_1, ECDSA_CURVES, CURVE_NAMES
from lbryschema.validator import get_key_type_from_dem


class _ECDSAKeyHelper(object):
    def __init__(self, key):
        self._key = key

    @property
    def der(self):
        return self._key.to_der()

    @property
    def curve_name(self):
        return self._key.curve.name


class Certificate(Schema):
    @classmethod
    def load(cls, message):
        _key = deepcopy(message)
        _message_pb = cert_pb.Certificate()
        if isinstance(_key, dict):
            _message_pb.publicKey = _key.pop("publicKey")
            _message_pb.version = VERSION_MAP[_key.pop("version")]
            _message_pb.keyType = ECDSA_CURVES[_key.pop("keyType")]
        else:
            _message_pb.version = _key.version
            _message_pb.keyType = _key.keyType
            _message_pb.publicKey = _key.publicKey
        if _message_pb.keyType not in CURVE_NAMES:
            raise Exception("Unknown curve")
        if get_key_type_from_dem(_message_pb.publicKey) != _message_pb.keyType:
            raise Exception("Curve mismatch")
        return cls._load(_key, _message_pb)

    @classmethod
    def load_from_key_obj(cls, key, key_type):
        if key_type in ECDSA_CURVES:
            _key = _ECDSAKeyHelper(key)
        else:
            raise Exception("Unknown key type: %s" % str(type(key)))
        if key_type != _key.curve_name:
            raise Exception("Curve mismatch")
        msg = {
            "version": V_0_0_1,
            "keyType": key_type,
            "publicKey": _key.der,
        }
        return cls.load(msg)
