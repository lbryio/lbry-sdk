import base64
import struct
from typing import List
from binascii import hexlify

from google.protobuf.message import DecodeError

from lbrynet.schema.types.v2.result_pb2 import Outputs as OutputsMessage


class Outputs:

    __slots__ = 'txos', 'txs', 'offset', 'total'

    def __init__(self, txos: List, txs: List, offset: int, total: int):
        self.txos = txos
        self.txs = txs
        self.offset = offset
        self.total = total

    def _inflate_claim(self, txo, message):
        txo.meta = {
            'is_controlling': message.is_controlling,
            'activation_height': message.activation_height,
            'effective_amount': message.effective_amount,
            'trending_amount': message.trending_amount,
        }
        try:
            if txo.claim.is_channel:
                txo.meta['claims_in_channel'] = message.claims_in_channel
        except DecodeError:
            pass

    def inflate(self, txs):
        tx_map, txos = {tx.hash: tx for tx in txs}, []
        for txo_message in self.txos:
            if txo_message.WhichOneof('meta') == 'error':
                txos.append(None)
                continue
            txo = tx_map[txo_message.tx_hash].outputs[txo_message.nout]
            if txo_message.WhichOneof('meta') == 'claim':
                self._inflate_claim(txo, txo_message.claim)
                if txo_message.claim.HasField('channel'):
                    channel_message = txo_message.claim.channel
                    txo.channel = tx_map[channel_message.tx_hash].outputs[channel_message.nout]
                    self._inflate_claim(txo.channel, channel_message.claim)
            txos.append(txo)
        return txos

    @classmethod
    def from_base64(cls, data: str) -> 'Outputs':
        return cls.from_bytes(base64.b64decode(data))

    @classmethod
    def from_bytes(cls, data: bytes) -> 'Outputs':
        outputs = OutputsMessage()
        outputs.ParseFromString(data)
        txs = {}
        for txo_message in outputs.txos:
            if txo_message.WhichOneof('meta') == 'error':
                continue
            txs[txo_message.tx_hash] = (hexlify(txo_message.tx_hash[::-1]).decode(), txo_message.height)
            if txo_message.WhichOneof('meta') == 'claim' and txo_message.claim.HasField('channel'):
                channel = txo_message.claim.channel
                txs[channel.tx_hash] = (hexlify(channel.tx_hash[::-1]).decode(), channel.height)
        return cls(outputs.txos, list(txs.values()), outputs.offset, outputs.total)

    @classmethod
    def to_base64(cls, txo_rows, offset=0, total=None) -> str:
        return base64.b64encode(cls.to_bytes(txo_rows, offset, total)).decode()

    @classmethod
    def to_bytes(cls, txo_rows, offset=0, total=None) -> bytes:
        page = OutputsMessage()
        page.offset = offset
        page.total = total or len(txo_rows)
        for txo in txo_rows:
            txo_message = page.txos.add()
            if isinstance(txo, Exception):
                txo_message.error.text = txo.args[0]
                if isinstance(txo, ValueError):
                    txo_message.error.code = txo_message.error.INVALID
                elif isinstance(txo, LookupError):
                    txo_message.error.code = txo_message.error.NOT_FOUND
                continue
            txo_message.height = txo['height']
            txo_message.tx_hash = txo['txo_hash'][:32]
            txo_message.nout, = struct.unpack('<I', txo['txo_hash'][32:])
            txo_message.claim.is_controlling = bool(txo['is_controlling'])
            txo_message.claim.activation_height = txo['activation_height']
            txo_message.claim.effective_amount = txo['effective_amount']
            txo_message.claim.trending_amount = txo['trending_amount']
            txo_message.claim.claims_in_channel = txo['claims_in_channel']
            if txo['channel_txo_hash']:
                channel = txo_message.claim.channel
                channel.height = txo['channel_height']
                channel.tx_hash = txo['channel_txo_hash'][:32]
                channel.nout, = struct.unpack('<I', txo['channel_txo_hash'][32:])
                channel.claim.activation_height = txo['channel_activation_height']
                channel.claim.effective_amount = txo['channel_effective_amount']
                channel.claim.trending_amount = txo['channel_trending_amount']
        return page.SerializeToString()
