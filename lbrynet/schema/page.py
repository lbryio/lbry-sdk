import base64
import struct
from typing import List

from lbrynet.schema.types.v2.page_pb2 import Page as PageMessage
from lbrynet.wallet.transaction import Transaction, Output


class Page:

    __slots__ = 'txs', 'txos', 'offset', 'total'

    def __init__(self, txs, txos, offset, total):
        self.txs: List[Transaction] = txs
        self.txos: List[Output] = txos
        self.offset = offset
        self.total = total

    @classmethod
    def from_base64(cls, data: str) -> 'Page':
        return cls.from_bytes(base64.b64decode(data))

    @classmethod
    def from_bytes(cls, data: bytes) -> 'Page':
        page_message = PageMessage()
        page_message.ParseFromString(data)
        tx_map, txo_list = {}, []
        for tx_message in page_message.txs:
            tx = Transaction(tx_message.raw, height=tx_message.height, position=tx_message.position)
            tx_map[tx.hash] = tx
        for txo_message in page_message.txos:
            output = tx_map[txo_message.tx_hash].outputs[txo_message.nout]
            if txo_message.WhichOneof('meta') == 'claim':
                claim = txo_message.claim
                output.meta = {
                    'is_winning': claim.is_winning,
                    'effective_amount': claim.effective_amount,
                    'trending_amount': claim.trending_amount,
                }
                if claim.HasField('channel'):
                    output.channel = tx_map[claim.channel.tx_hash].outputs[claim.channel.nout]
            txo_list.append(output)
        return cls(list(tx_map.values()), txo_list, page_message.offset, page_message.total)

    @classmethod
    def to_base64(cls, tx_rows, txo_rows, offset, total) -> str:
        return base64.b64encode(cls.to_bytes(tx_rows, txo_rows, offset, total)).decode()

    @classmethod
    def to_bytes(cls, tx_rows, txo_rows, offset, total) -> bytes:
        page = PageMessage()
        page.total = total
        page.offset = offset
        for tx in tx_rows:
            tx_message = page.txs.add()
            tx_message.raw = tx['raw']
            tx_message.height = tx['height']
            tx_message.position = tx['position']
        for txo in txo_rows:
            txo_message = page.txos.add()
            txo_message.tx_hash = txo['txo_hash'][:32]
            txo_message.nout, = struct.unpack('<I', txo['txo_hash'][32:])
            if 'channel_txo_hash' in txo and txo['channel_txo_hash']:
                txo_message.claim.channel.tx_hash = txo['channel_txo_hash'][:32]
                txo_message.claim.channel.nout, = struct.unpack('<I', txo['channel_txo_hash'][32:])
            if 'is_winning' in txo:  # claim
                txo_message.claim.is_winning = bool(txo['is_winning'])
                txo_message.claim.activation_height = txo['activation_height']
                txo_message.claim.effective_amount = txo['effective_amount']
                txo_message.claim.trending_amount = txo['trending_amount']
        return page.SerializeToString()
