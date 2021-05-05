import base64
import struct
from typing import List, TYPE_CHECKING, Union
from binascii import hexlify
from itertools import chain

from lbry.error import ResolveCensoredError
from lbry.schema.types.v2.result_pb2 import Outputs as OutputsMessage
from lbry.schema.types.v2.result_pb2 import Error as ErrorMessage
if TYPE_CHECKING:
    from lbry.wallet.server.leveldb import ResolveResult

INVALID = ErrorMessage.Code.Name(ErrorMessage.INVALID)
NOT_FOUND = ErrorMessage.Code.Name(ErrorMessage.NOT_FOUND)
BLOCKED = ErrorMessage.Code.Name(ErrorMessage.BLOCKED)


def set_reference(reference, claim_hash, rows):
    if claim_hash:
        for txo in rows:
            if claim_hash == txo.claim_hash:
                reference.tx_hash = txo.tx_hash
                reference.nout = txo.position
                reference.height = txo.height
                return


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
        page = OutputsMessage()
        page.offset = offset
        if total is not None:
            page.total = total
        # if blocked is not None:
        #     blocked.to_message(page, extra_txo_rows)
        for row in extra_txo_rows:
            cls.encode_txo(page.extra_txos.add(), row)

        for row in txo_rows:
            # cls.row_to_message(row, page.txos.add(), extra_txo_rows)
            txo_message: 'OutputsMessage' = page.txos.add()
            cls.encode_txo(txo_message, row)
            if not isinstance(row, Exception):
                if row.channel_hash:
                    set_reference(txo_message.claim.channel, row.channel_hash, extra_txo_rows)
                if row.reposted_claim_hash:
                    set_reference(txo_message.claim.repost, row.reposted_claim_hash, extra_txo_rows)
                # set_reference(txo_message.error.blocked.channel, row.censor_hash, extra_txo_rows)
        return page.SerializeToString()

    @classmethod
    def encode_txo(cls, txo_message, resolve_result: Union['ResolveResult', Exception]):
        if isinstance(resolve_result, Exception):
            txo_message.error.text = resolve_result.args[0]
            if isinstance(resolve_result, ValueError):
                txo_message.error.code = ErrorMessage.INVALID
            elif isinstance(resolve_result, LookupError):
                txo_message.error.code = ErrorMessage.NOT_FOUND
            elif isinstance(resolve_result, ResolveCensoredError):
                txo_message.error.code = ErrorMessage.BLOCKED
            return
        txo_message.tx_hash = resolve_result.tx_hash
        txo_message.nout = resolve_result.position
        txo_message.height = resolve_result.height
        txo_message.claim.short_url = resolve_result.short_url
        txo_message.claim.reposted = 0
        txo_message.claim.is_controlling = resolve_result.is_controlling
        txo_message.claim.creation_height = resolve_result.creation_height
        txo_message.claim.activation_height = resolve_result.activation_height
        txo_message.claim.expiration_height = resolve_result.expiration_height
        txo_message.claim.effective_amount = resolve_result.effective_amount
        txo_message.claim.support_amount = resolve_result.support_amount

        if resolve_result.canonical_url is not None:
            txo_message.claim.canonical_url = resolve_result.canonical_url
        if resolve_result.last_takeover_height is not None:
            txo_message.claim.take_over_height = resolve_result.last_takeover_height
        if resolve_result.claims_in_channel is not None:
            txo_message.claim.claims_in_channel = resolve_result.claims_in_channel
