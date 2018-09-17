import json
import google.protobuf.json_format as json_pb  # pylint: disable=no-name-in-module
from google.protobuf.message import Message  # pylint: disable=no-name-in-module,import-error


class Schema(Message):
    @classmethod
    def load(cls, message):
        raise NotImplementedError

    @classmethod
    def _load(cls, data, message):
        if isinstance(data, dict):
            data = json.dumps(data)
        return json_pb.Parse(data, message)
