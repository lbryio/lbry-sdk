import base64
import struct
from typing import List
from binascii import hexlify
from itertools import chain

from lbry.error import ResolveCensoredError
from lbry.schema.types.v2.result_pb2 import Outputs as OutputsMessage
from lbry.schema.types.v2.result_pb2 import Error as ErrorMessage

INVALID = ErrorMessage.Code.Name(ErrorMessage.INVALID)
NOT_FOUND = ErrorMessage.Code.Name(ErrorMessage.NOT_FOUND)
BLOCKED = ErrorMessage.Code.Name(ErrorMessage.BLOCKED)


def set_reference(reference, txo_row):
    if txo_row:
        reference.tx_hash = txo_row['txo_hash'][:32]
        reference.nout = struct.unpack('<I', txo_row['txo_hash'][32:])[0]
        reference.height = txo_row['height']


class Censor:

    NOT_CENSORED = 0
    SEARCH = 1
    RESOLVE = 2

    __slots__ = 'censor_type', 'censored'

    def __init__(self, censor_type):
        self.censor_type = censor_type
        self.censored = {}

    def is_censored(self, row):
        return (row.get('censor_type') or self.NOT_CENSORED) >= self.censor_type

    def apply(self, rows):
        return [row for row in rows if not self.censor(row)]

    def censor(self, row) -> bool:
        if self.is_censored(row):
            censoring_channel_hash = row['censoring_channel_hash']
            self.censored.setdefault(censoring_channel_hash, set())
            self.censored[censoring_channel_hash].add(row['tx_hash'])
            return True
        return False

    def to_message(self, outputs: OutputsMessage, extra_txo_rows: dict):
        for censoring_channel_hash, count in self.censored.items():
            blocked = outputs.blocked.add()
            blocked.count = len(count)
            set_reference(blocked.channel, extra_txo_rows.get(censoring_channel_hash))
            outputs.blocked_total += len(count)


class Outputs:

    __slots__ = 'txos', 'extra_txos', 'txs', 'offset', 'total', 'blocked', 'blocked_total'

    def __init__(self, txos: List, extra_txos: List, txs: set,
                 offset: int, total: int, blocked: List, blocked_total: int):
        self.txos = txos
        self.txs = txs
        self.extra_txos = extra_txos
        self.offset = offset
        self.total = total
        self.blocked = blocked
        self.blocked_total = blocked_total

    def inflate(self, txs):
        tx_map = {tx.hash: tx for tx in txs}
        for txo_message in self.extra_txos:
            self.message_to_txo(txo_message, tx_map)
        txos = [self.message_to_txo(txo_message, tx_map) for txo_message in self.txos]
        return txos, self.inflate_blocked(tx_map)

    def inflate_blocked(self, tx_map):
        return {
            "total": self.blocked_total,
            "channels": [{
                'channel': self.message_to_txo(blocked.channel, tx_map),
                'blocked': blocked.count
            } for blocked in self.blocked]
        }

    def message_to_txo(self, txo_message, tx_map):
        if txo_message.WhichOneof('meta') == 'error':
            error = {
                'error': {
                    'name': txo_message.error.Code.Name(txo_message.error.code),
                    'text': txo_message.error.text,
                }
            }
            if error['error']['name'] == BLOCKED:
                error['error']['censor'] = self.message_to_txo(
                    txo_message.error.blocked.channel, tx_map
                )
            return error

        tx = tx_map.get(txo_message.tx_hash)
        if not tx:
            return
        txo = tx.outputs[txo_message.nout]
        if txo_message.WhichOneof('meta') == 'claim':
            claim = txo_message.claim
            txo.meta = {
                'short_url': f'lbry://{claim.short_url}',
                'canonical_url': f'lbry://{claim.canonical_url or claim.short_url}',
                'reposted': claim.reposted,
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
            if claim.HasField('repost'):
                txo.reposted_claim = tx_map[claim.repost.tx_hash].outputs[claim.repost.nout]
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
        return cls(
            outputs.txos, outputs.extra_txos, txs,
            outputs.offset, outputs.total,
            outputs.blocked, outputs.blocked_total
        )

    @classmethod
    def to_base64(cls, txo_rows, extra_txo_rows, offset=0, total=None, blocked=None) -> str:
        return base64.b64encode(cls.to_bytes(txo_rows, extra_txo_rows, offset, total, blocked)).decode()

    @classmethod
    def to_bytes(cls, txo_rows, extra_txo_rows, offset=0, total=None, blocked: Censor = None) -> bytes:
        extra_txo_rows = {row['claim_hash']: row for row in extra_txo_rows}
        page = OutputsMessage()
        page.offset = offset
        if total is not None:
            page.total = total
        if blocked is not None:
            blocked.to_message(page, extra_txo_rows)
        for row in txo_rows:
            cls.row_to_message(row, page.txos.add(), extra_txo_rows)
        for row in extra_txo_rows.values():
            cls.row_to_message(row, page.extra_txos.add(), extra_txo_rows)
        return page.SerializeToString()

    @classmethod
    def row_to_message(cls, txo, txo_message, extra_row_dict: dict):
        if isinstance(txo, Exception):
            txo_message.error.text = txo.args[0]
            if isinstance(txo, ValueError):
                txo_message.error.code = ErrorMessage.INVALID
            elif isinstance(txo, LookupError):
                txo_message.error.code = ErrorMessage.NOT_FOUND
            elif isinstance(txo, ResolveCensoredError):
                txo_message.error.code = ErrorMessage.BLOCKED
                set_reference(txo_message.error.blocked.channel, extra_row_dict.get(txo.censor_hash))
            return
        txo_message.tx_hash = txo['txo_hash'][:32]
        txo_message.nout, = struct.unpack('<I', txo['txo_hash'][32:])
        txo_message.height = txo['height']
        txo_message.claim.short_url = txo['short_url']
        txo_message.claim.reposted = txo['reposted']
        if txo['canonical_url'] is not None:
            txo_message.claim.canonical_url = txo['canonical_url']
        txo_message.claim.is_controlling = bool(txo['is_controlling'])
        if txo['last_take_over_height'] is not None:
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
        set_reference(txo_message.claim.channel, extra_row_dict.get(txo['channel_hash']))
        set_reference(txo_message.claim.repost, extra_row_dict.get(txo['reposted_claim_hash']))
