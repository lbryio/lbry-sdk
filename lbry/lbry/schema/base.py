from binascii import hexlify, unhexlify
from typing import List, Iterator, TypeVar, Generic

from google.protobuf.message import DecodeError
from google.protobuf.json_format import MessageToDict


class Signable:

    __slots__ = (
        'message', 'version', 'signature',
        'signature_type', 'unsigned_payload', 'signing_channel_hash'
    )

    message_class = None

    def __init__(self, message=None):
        self.message = message or self.message_class()
        self.version = 2
        self.signature = None
        self.signature_type = 'SECP256k1'
        self.unsigned_payload = None
        self.signing_channel_hash = None

    def clear_signature(self):
        self.signature = None
        self.unsigned_payload = None
        self.signing_channel_hash = None

    @property
    def signing_channel_id(self):
        return hexlify(self.signing_channel_hash[::-1]).decode() if self.signing_channel_hash else None

    @signing_channel_id.setter
    def signing_channel_id(self, channel_id: str):
        self.signing_channel_hash = unhexlify(channel_id)[::-1]

    @property
    def is_signed(self):
        return self.signature is not None

    def to_dict(self):
        return MessageToDict(self.message)

    def to_message_bytes(self) -> bytes:
        return self.message.SerializeToString()

    def to_bytes(self) -> bytes:
        pieces = bytearray()
        if self.is_signed:
            pieces.append(1)
            pieces.extend(self.signing_channel_hash)
            pieces.extend(self.signature)
        else:
            pieces.append(0)
        pieces.extend(self.to_message_bytes())
        return bytes(pieces)

    @classmethod
    def from_bytes(cls, data: bytes):
        signable = cls()
        if data[0] == 0:
            signable.message.ParseFromString(data[1:])
        elif data[0] == 1:
            signable.signing_channel_hash = data[1:21]
            signable.signature = data[21:85]
            signable.message.ParseFromString(data[85:])
        else:
            raise DecodeError('Could not determine message format version.')
        return signable

    def __len__(self):
        return len(self.to_bytes())

    def __bytes__(self):
        return self.to_bytes()


class Metadata:

    __slots__ = 'message',

    def __init__(self, message):
        self.message = message


I = TypeVar('I')


class BaseMessageList(Metadata, Generic[I]):

    __slots__ = ()

    item_class = None

    @property
    def _message(self):
        return self.message

    def add(self) -> I:
        return self.item_class(self._message.add())

    def extend(self, values: List[str]):
        for value in values:
            self.append(value)

    def append(self, value: str):
        raise NotImplemented

    def __len__(self):
        return len(self._message)

    def __iter__(self) -> Iterator[I]:
        for item in self._message:
            yield self.item_class(item)

    def __getitem__(self, item) -> I:
        return self.item_class(self._message[item])

    def __delitem__(self, key):
        del self._message[key]

    def __eq__(self, other) -> bool:
        return self._message == other
