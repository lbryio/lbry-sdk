from google.protobuf.message import DecodeError
from google.protobuf.json_format import MessageToDict
from lbry_types.v2.purchase_pb2 import Purchase as PurchaseMessage
from .attrs import ClaimReference


class Purchase(ClaimReference):

    START_BYTE = ord('P')

    __slots__ = ()

    def __init__(self, claim_id=None):
        super().__init__(PurchaseMessage())
        if claim_id is not None:
            self.claim_id = claim_id

    def to_dict(self):
        return MessageToDict(self.message)

    def to_message_bytes(self) -> bytes:
        return self.message.SerializeToString()

    def to_bytes(self) -> bytes:
        pieces = bytearray()
        pieces.append(self.START_BYTE)
        pieces.extend(self.to_message_bytes())
        return bytes(pieces)

    @classmethod
    def has_start_byte(cls, data: bytes):
        return data and data[0] == cls.START_BYTE

    @classmethod
    def from_bytes(cls, data: bytes):
        purchase = cls()
        if purchase.has_start_byte(data):
            purchase.message.ParseFromString(data[1:])
        else:
            raise DecodeError('Message does not start with correct byte.')
        return purchase

    def __len__(self):
        return len(self.to_bytes())

    def __bytes__(self):
        return self.to_bytes()
