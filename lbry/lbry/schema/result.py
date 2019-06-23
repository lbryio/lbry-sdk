import base64
import struct
from typing import List
from binascii import hexlify
from itertools import chain

from lbry.schema.types.v2.result_pb2 import Outputs as OutputsMessage


class Outputs:

    __slots__ = 'txos', 'extra_txos', 'txs', 'offset', 'total'

    def __init__(self, txos: List, extra_txos: List, txs: set, offset: int, total: int):
        self.txos = txos
        self.txs = txs
        self.extra_txos = extra_txos
        self.offset = offset
        self.total = total

    def inflate(self, txs):
        tx_map = {tx.hash: tx for tx in txs}
        for txo_message in self.extra_txos:
            self.message_to_txo(txo_message, tx_map)
        return [self.message_to_txo(txo_message, tx_map) for txo_message in self.txos]

    def message_to_txo(self, txo_message, tx_map):
        if txo_message.WhichOneof('meta') == 'error':
            return None
        txo = tx_map[txo_message.tx_hash].outputs[txo_message.nout]
        if txo_message.WhichOneof('meta') == 'claim':
            claim = txo_message.claim
            txo.meta = {
                'short_url': f'lbry://{claim.short_url}',
                'canonical_url': f'lbry://{claim.canonical_url or claim.short_url}',
                'is_controlling': claim.is_controlling,
                'take_over_height': claim.take_over_height,
                'creation_height': claim.creation_height,
                'activation_height': claim.activation_height,
                'expiration_height': claim.expiration_height,
                'effective_amount': claim.effective_amount,
                'support_amount': claim.support_amount,
                'trending_group': claim.trending_group,
                'trending_mixed': claim.trending_mixed,
                'trending_local': claim.trending_local,
                'trending_global': claim.trending_global,
            }
            if claim.HasField('channel'):
                txo.channel = tx_map[claim.channel.tx_hash].outputs[claim.channel.nout]
            try:
                if txo.claim.is_channel:
                    txo.meta['claims_in_channel'] = claim.claims_in_channel
            except:
                pass
        return txo

    @classmethod
    def from_base64(cls, data: str) -> 'Outputs':
        return cls.from_bytes(base64.b64decode(data))

    @classmethod
    def from_bytes(cls, data: bytes) -> 'Outputs':
        outputs = OutputsMessage()
        outputs.ParseFromString(data)
        txs = set()
        for txo_message in chain(outputs.txos, outputs.extra_txos):
            if txo_message.WhichOneof('meta') == 'error':
                continue
            txs.add((hexlify(txo_message.tx_hash[::-1]).decode(), txo_message.height))
        return cls(outputs.txos, outputs.extra_txos, txs, outputs.offset, outputs.total)

    @classmethod
    def to_base64(cls, txo_rows, extra_txo_rows, offset=0, total=None) -> str:
        return base64.b64encode(cls.to_bytes(txo_rows, extra_txo_rows, offset, total)).decode()

    @classmethod
    def to_bytes(cls, txo_rows, extra_txo_rows, offset=0, total=None) -> bytes:
        page = OutputsMessage()
        page.offset = offset
        page.total = total or len(txo_rows)
        for row in txo_rows:
            cls.row_to_message(row, page.txos.add())
        for row in extra_txo_rows:
            cls.row_to_message(row, page.extra_txos.add())
        return page.SerializeToString()

    @classmethod
    def row_to_message(cls, txo, txo_message):
        if isinstance(txo, Exception):
            txo_message.error.text = txo.args[0]
            if isinstance(txo, ValueError):
                txo_message.error.code = txo_message.error.INVALID
            elif isinstance(txo, LookupError):
                txo_message.error.code = txo_message.error.NOT_FOUND
            return
        txo_message.tx_hash = txo['txo_hash'][:32]
        txo_message.nout, = struct.unpack('<I', txo['txo_hash'][32:])
        txo_message.height = txo['height']
        txo_message.claim.short_url = txo['short_url']
        if txo['canonical_url'] is not None:
            txo_message.claim.canonical_url = txo['canonical_url']
        txo_message.claim.is_controlling = bool(txo['is_controlling'])
        txo_message.claim.take_over_height = txo['last_take_over_height']
        txo_message.claim.creation_height = txo['creation_height']
        txo_message.claim.activation_height = txo['activation_height']
        txo_message.claim.expiration_height = txo['expiration_height']
        if txo['claims_in_channel'] is not None:
            txo_message.claim.claims_in_channel = txo['claims_in_channel']
        txo_message.claim.effective_amount = txo['effective_amount']
        txo_message.claim.support_amount = txo['support_amount']
        txo_message.claim.trending_group = txo['trending_group']
        txo_message.claim.trending_mixed = txo['trending_mixed']
        txo_message.claim.trending_local = txo['trending_local']
        txo_message.claim.trending_global = txo['trending_global']
        if txo['channel_txo_hash']:
            channel = txo_message.claim.channel
            channel.tx_hash = txo['channel_txo_hash'][:32]
            channel.nout, = struct.unpack('<I', txo['channel_txo_hash'][32:])
            channel.height = txo['channel_height']
