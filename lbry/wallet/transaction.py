import struct
import hashlib
import logging
import typing
import asyncio
from binascii import hexlify, unhexlify
from typing import List, Iterable, Optional, Tuple

import ecdsa
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import load_der_public_key
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from cryptography.exceptions import InvalidSignature

from lbry.error import InsufficientFundsError
from lbry.crypto.hash import hash160, sha256
from lbry.crypto.base58 import Base58
from lbry.schema.url import normalize_name
from lbry.schema.claim import Claim
from lbry.schema.base import Signable
from lbry.schema.purchase import Purchase
from lbry.schema.support import Support

from .script import InputScript, OutputScript
from .constants import COIN, DUST, NULL_HASH32
from .bcd_data_stream import BCDataStream
from .hash import TXRef, TXRefImmutable
from .util import ReadOnlyList

if typing.TYPE_CHECKING:
    from lbry.wallet.account import Account
    from lbry.wallet.ledger import Ledger
    from lbry.wallet.wallet import Wallet

log = logging.getLogger()


class TXRefMutable(TXRef):

    __slots__ = ('tx',)

    def __init__(self, tx: 'Transaction') -> None:
        super().__init__()
        self.tx = tx

    @property
    def id(self):
        if self._id is None:
            self._id = hexlify(self.hash[::-1]).decode()
        return self._id

    @property
    def hash(self):
        if self._hash is None:
            self._hash = sha256(sha256(self.tx.raw_sans_segwit))
        return self._hash

    @property
    def height(self):
        return self.tx.height

    def reset(self):
        self._id = None
        self._hash = None


class TXORef:

    __slots__ = 'tx_ref', 'position'

    def __init__(self, tx_ref: TXRef, position: int) -> None:
        self.tx_ref = tx_ref
        self.position = position

    @property
    def id(self):
        return f'{self.tx_ref.id}:{self.position}'

    @property
    def hash(self):
        return self.tx_ref.hash + BCDataStream.uint32.pack(self.position)

    @property
    def is_null(self):
        return self.tx_ref.is_null

    @property
    def txo(self) -> Optional['Output']:
        return None


class TXORefResolvable(TXORef):

    __slots__ = ('_txo',)

    def __init__(self, txo: 'Output') -> None:
        assert txo.tx_ref is not None
        assert txo.position is not None
        super().__init__(txo.tx_ref, txo.position)
        self._txo = txo

    @property
    def txo(self):
        return self._txo


class InputOutput:

    __slots__ = 'tx_ref', 'position'

    def __init__(self, tx_ref: TXRef = None, position: int = None) -> None:
        self.tx_ref = tx_ref
        self.position = position

    @property
    def size(self) -> int:
        """ Size of this input / output in bytes. """
        stream = BCDataStream()
        self.serialize_to(stream)
        return len(stream.get_bytes())

    def get_fee(self, ledger):
        return self.size * ledger.fee_per_byte

    def serialize_to(self, stream, alternate_script=None):
        raise NotImplementedError


class Input(InputOutput):

    NULL_SIGNATURE = b'\x00'*72
    NULL_PUBLIC_KEY = b'\x00'*33

    __slots__ = 'txo_ref', 'sequence', 'coinbase', 'script'

    def __init__(self, txo_ref: TXORef, script: InputScript, sequence: int = 0xFFFFFFFF,
                 tx_ref: TXRef = None, position: int = None) -> None:
        super().__init__(tx_ref, position)
        self.txo_ref = txo_ref
        self.sequence = sequence
        self.coinbase = script if txo_ref.is_null else None
        self.script = script if not txo_ref.is_null else None

    @property
    def is_coinbase(self):
        return self.coinbase is not None

    @classmethod
    def spend(cls, txo: 'Output') -> 'Input':
        """ Create an input to spend the output."""
        assert txo.script.is_pay_pubkey_hash, 'Attempting to spend unsupported output.'
        script = InputScript.redeem_pubkey_hash(cls.NULL_SIGNATURE, cls.NULL_PUBLIC_KEY)
        return cls(txo.ref, script)

    @property
    def amount(self) -> int:
        """ Amount this input adds to the transaction. """
        if self.txo_ref.txo is None:
            raise ValueError('Cannot resolve output to get amount.')
        return self.txo_ref.txo.amount

    @property
    def is_my_input(self) -> Optional[bool]:
        """ True if the output this input spends is yours. """
        if self.txo_ref.txo is None:
            return False
        return self.txo_ref.txo.is_my_output

    @classmethod
    def deserialize_from(cls, stream):
        tx_ref = TXRefImmutable.from_hash(stream.read(32), -1)
        position = stream.read_uint32()
        script = stream.read_string()
        sequence = stream.read_uint32()
        return cls(
            TXORef(tx_ref, position),
            InputScript(script) if not tx_ref.is_null else script,
            sequence
        )

    def serialize_to(self, stream, alternate_script=None):
        stream.write(self.txo_ref.tx_ref.hash)
        stream.write_uint32(self.txo_ref.position)
        if alternate_script is not None:
            stream.write_string(alternate_script)
        else:
            if self.is_coinbase:
                stream.write_string(self.coinbase)
            else:
                stream.write_string(self.script.source)
        stream.write_uint32(self.sequence)


class OutputEffectiveAmountEstimator:

    __slots__ = 'txo', 'txi', 'fee', 'effective_amount'

    def __init__(self, ledger: 'Ledger', txo: 'Output') -> None:
        self.txo = txo
        self.txi = Input.spend(txo)
        self.fee: int = self.txi.get_fee(ledger)
        self.effective_amount: int = txo.amount - self.fee

    def __lt__(self, other):
        return self.effective_amount < other.effective_amount


class Output(InputOutput):

    __slots__ = (
        'amount', 'script', 'is_internal_transfer', 'is_spent', 'is_my_output', 'is_my_input',
        'channel', 'private_key', 'meta', 'sent_supports', 'sent_tips', 'received_tips',
        'purchase', 'purchased_claim', 'purchase_receipt',
        'reposted_claim', 'claims', '_signable'
    )

    def __init__(self, amount: int, script: OutputScript,
                 tx_ref: TXRef = None, position: int = None,
                 is_internal_transfer: Optional[bool] = None, is_spent: Optional[bool] = None,
                 is_my_output: Optional[bool] = None, is_my_input: Optional[bool] = None,
                 sent_supports: Optional[int] = None, sent_tips: Optional[int] = None,
                 received_tips: Optional[int] = None,
                 channel: Optional['Output'] = None, private_key: Optional[str] = None
                 ) -> None:
        super().__init__(tx_ref, position)
        self.amount = amount
        self.script = script
        self.is_internal_transfer = is_internal_transfer
        self.is_spent = is_spent
        self.is_my_output = is_my_output
        self.is_my_input = is_my_input
        self.sent_supports = sent_supports
        self.sent_tips = sent_tips
        self.received_tips = received_tips
        self.channel = channel
        self.private_key = private_key
        self.purchase: 'Output' = None  # txo containing purchase metadata
        self.purchased_claim: 'Output' = None  # resolved claim pointed to by purchase
        self.purchase_receipt: 'Output' = None  # txo representing purchase receipt for this claim
        self.reposted_claim: 'Output' = None  # txo representing claim being reposted
        self.claims: List['Output'] = None  # resolved claims for collection
        self._signable: Optional[Signable] = None
        self.meta = {}

    def update_annotations(self, annotated: 'Output'):
        if annotated is None:
            self.is_internal_transfer = None
            self.is_spent = None
            self.is_my_output = None
            self.is_my_input = None
            self.sent_supports = None
            self.sent_tips = None
            self.received_tips = None
        else:
            self.is_internal_transfer = annotated.is_internal_transfer
            self.is_spent = annotated.is_spent
            self.is_my_output = annotated.is_my_output
            self.is_my_input = annotated.is_my_input
            self.sent_supports = annotated.sent_supports
            self.sent_tips = annotated.sent_tips
            self.received_tips = annotated.received_tips
        self.channel = annotated.channel if annotated else None
        self.private_key = annotated.private_key if annotated else None

    @property
    def ref(self):
        return TXORefResolvable(self)

    @property
    def id(self):
        return self.ref.id

    @property
    def is_pubkey_hash(self):
        return 'pubkey_hash' in self.script.values

    @property
    def pubkey_hash(self):
        return self.script.values['pubkey_hash']

    @property
    def is_script_hash(self):
        return 'script_hash' in self.script.values

    @property
    def script_hash(self):
        return self.script.values['script_hash']

    @property
    def has_address(self):
        return self.is_pubkey_hash or self.is_script_hash

    def get_address(self, ledger):
        if self.is_pubkey_hash:
            return ledger.hash160_to_address(self.pubkey_hash)
        elif self.is_script_hash:
            return ledger.hash160_to_script_address(self.script_hash)

    def get_estimator(self, ledger):
        return OutputEffectiveAmountEstimator(ledger, self)

    @classmethod
    def pay_pubkey_hash(cls, amount, pubkey_hash):
        return cls(amount, OutputScript.pay_pubkey_hash(pubkey_hash))

    @classmethod
    def pay_script_hash(cls, amount, pubkey_hash):
        return cls(amount, OutputScript.pay_script_hash(pubkey_hash))

    @classmethod
    def deserialize_from(cls, stream):
        return cls(
            amount=stream.read_uint64(),
            script=OutputScript(stream.read_string())
        )

    def serialize_to(self, stream, alternate_script=None):
        stream.write_uint64(self.amount)
        stream.write_string(self.script.source)

    def get_fee(self, ledger):
        name_fee = 0
        if self.script.is_claim_name:
            name_fee = len(self.script.values['claim_name']) * ledger.fee_per_name_char
        return max(name_fee, super().get_fee(ledger))

    @property
    def is_claim(self) -> bool:
        return self.script.is_claim_name or self.script.is_update_claim

    @property
    def is_support(self) -> bool:
        return self.script.is_support_claim

    @property
    def is_support_data(self) -> bool:
        return self.script.is_support_claim_data

    @property
    def claim_hash(self) -> bytes:
        if self.script.is_claim_name:
            return hash160(self.tx_ref.hash + struct.pack('>I', self.position))
        elif self.script.is_update_claim or self.script.is_support_claim:
            return self.script.values['claim_id']
        else:
            raise ValueError('No claim_id associated.')

    @property
    def claim_id(self) -> str:
        return hexlify(self.claim_hash[::-1]).decode()

    @property
    def claim_name(self) -> str:
        if self.script.is_claim_involved:
            return self.script.values['claim_name'].decode()
        raise ValueError('No claim_name associated.')

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.claim_name)

    @property
    def claim(self) -> Claim:
        if self.is_claim:
            if not isinstance(self.script.values['claim'], Claim):
                self.script.values['claim'] = Claim.from_bytes(self.script.values['claim'])
            return self.script.values['claim']
        raise ValueError('Only claim name and claim update have the claim payload.')

    @property
    def can_decode_claim(self):
        try:
            return self.claim
        except Exception:
            return False

    @property
    def support(self) -> Support:
        if self.is_support_data:
            if not isinstance(self.script.values['support'], Support):
                self.script.values['support'] = Support.from_bytes(self.script.values['support'])
            return self.script.values['support']
        raise ValueError('Only supports with data can be represented as Supports.')

    @property
    def can_decode_support(self):
        try:
            return self.support
        except Exception:
            return False

    @property
    def signable(self) -> Signable:
        if self._signable is None:
            if self.is_claim:
                self._signable = self.claim
            elif self.is_support_data:
                self._signable = self.support
        return self._signable

    @property
    def permanent_url(self) -> str:
        if self.script.is_claim_involved:
            return f"lbry://{self.claim_name}#{self.claim_id}"
        raise ValueError('No claim associated.')

    @property
    def has_private_key(self):
        return self.private_key is not None

    def get_signature_digest(self, ledger):
        if self.signable.unsigned_payload:
            pieces = [
                Base58.decode(self.get_address(ledger)),
                self.signable.unsigned_payload,
                self.signable.signing_channel_hash[::-1]
            ]
        else:
            pieces = [
                self.tx_ref.tx.inputs[0].txo_ref.hash,
                self.signable.signing_channel_hash,
                self.signable.to_message_bytes()
            ]
        return sha256(b''.join(pieces))

    def get_encoded_signature(self):
        signature = hexlify(self.signable.signature)
        r = int(signature[:int(len(signature)/2)], 16)
        s = int(signature[int(len(signature)/2):], 16)
        return ecdsa.util.sigencode_der(r, s, len(signature)*4)

    @staticmethod
    def is_signature_valid(encoded_signature, signature_digest, public_key_bytes):
        try:
            public_key = load_der_public_key(public_key_bytes, default_backend())
            public_key.verify(encoded_signature, signature_digest, ec.ECDSA(Prehashed(hashes.SHA256())))
            return True
        except (ValueError, InvalidSignature):
            pass
        return False

    def is_signed_by(self, channel: 'Output', ledger=None):
        return self.is_signature_valid(
            self.get_encoded_signature(),
            self.get_signature_digest(ledger),
            channel.claim.channel.public_key_bytes
        )

    def sign(self, channel: 'Output', first_input_id=None):
        self.channel = channel
        self.signable.signing_channel_hash = channel.claim_hash
        digest = sha256(b''.join([
            first_input_id or self.tx_ref.tx.inputs[0].txo_ref.hash,
            self.signable.signing_channel_hash,
            self.signable.to_message_bytes()
        ]))
        self.signable.signature = channel.private_key.sign_digest_deterministic(digest, hashfunc=hashlib.sha256)
        self.script.generate()

    def sign_data(self, data:bytes, timestamp:str) -> str:
        pieces = [timestamp.encode(), self.claim_hash, data]
        digest = sha256(b''.join(pieces))
        signature = self.private_key.sign_digest_deterministic(digest, hashfunc=hashlib.sha256)
        return hexlify(signature).decode()

    def clear_signature(self):
        self.channel = None
        self.signable.clear_signature()

    async def generate_channel_private_key(self):
        self.private_key = await asyncio.get_event_loop().run_in_executor(
            None, ecdsa.SigningKey.generate, ecdsa.SECP256k1, None, hashlib.sha256
        )
        self.claim.channel.public_key_bytes = self.private_key.get_verifying_key().to_der()
        self.script.generate()
        return self.private_key

    def is_channel_private_key(self, private_key):
        return self.claim.channel.public_key_bytes == private_key.get_verifying_key().to_der()

    @classmethod
    def pay_claim_name_pubkey_hash(
            cls, amount: int, claim_name: str, claim: Claim, pubkey_hash: bytes) -> 'Output':
        script = OutputScript.pay_claim_name_pubkey_hash(
            claim_name.encode(), claim, pubkey_hash)
        return cls(amount, script)

    @classmethod
    def pay_update_claim_pubkey_hash(
            cls, amount: int, claim_name: str, claim_id: str, claim: Claim, pubkey_hash: bytes) -> 'Output':
        script = OutputScript.pay_update_claim_pubkey_hash(
            claim_name.encode(), unhexlify(claim_id)[::-1], claim, pubkey_hash
        )
        return cls(amount, script)

    @classmethod
    def pay_support_pubkey_hash(cls, amount: int, claim_name: str, claim_id: str, pubkey_hash: bytes) -> 'Output':
        script = OutputScript.pay_support_pubkey_hash(
            claim_name.encode(), unhexlify(claim_id)[::-1], pubkey_hash
        )
        return cls(amount, script)

    @classmethod
    def pay_support_data_pubkey_hash(
            cls, amount: int, claim_name: str, claim_id: str, support: Support, pubkey_hash: bytes) -> 'Output':
        script = OutputScript.pay_support_data_pubkey_hash(
            claim_name.encode(), unhexlify(claim_id)[::-1], support, pubkey_hash
        )
        return cls(amount, script)

    @classmethod
    def add_purchase_data(cls, purchase: Purchase) -> 'Output':
        script = OutputScript.return_data(purchase)
        return cls(0, script)

    @property
    def is_purchase_data(self) -> bool:
        return self.script.is_return_data and (
            isinstance(self.script.values['data'], Purchase) or
            Purchase.has_start_byte(self.script.values['data'])
        )

    @property
    def purchase_data(self) -> Purchase:
        if self.is_purchase_data:
            if not isinstance(self.script.values['data'], Purchase):
                self.script.values['data'] = Purchase.from_bytes(self.script.values['data'])
            return self.script.values['data']
        raise ValueError('Output does not have purchase data.')

    @property
    def can_decode_purchase_data(self):
        try:
            return self.purchase_data
        except:  # pylint: disable=bare-except
            return False

    @property
    def purchased_claim_id(self):
        if self.purchase is not None:
            return self.purchase.purchase_data.claim_id
        if self.purchased_claim is not None:
            return self.purchased_claim.claim_id

    @property
    def has_price(self):
        if self.can_decode_claim:
            claim = self.claim
            if claim.is_stream:
                stream = claim.stream
                return stream.has_fee and stream.fee.amount and stream.fee.amount > 0
        return False

    @property
    def price(self):
        return self.claim.stream.fee


class Transaction:

    def __init__(self, raw=None, version: int = 1, locktime: int = 0, is_verified: bool = False,
                 height: int = -2, position: int = -1, julian_day: int = None) -> None:
        self._raw = raw
        self._raw_sans_segwit = None
        self._raw_outputs = None
        self.is_segwit_flag = 0
        self.witnesses: List[bytes] = []
        self.ref = TXRefMutable(self)
        self.version = version
        self.locktime = locktime
        self._inputs: List[Input] = []
        self._outputs: List[Output] = []
        self.is_verified = is_verified
        # Height Progression
        #   -2: not broadcast
        #   -1: in mempool but has unconfirmed inputs
        #    0: in mempool and all inputs confirmed
        # +num: confirmed in a specific block (height)
        self.height = height
        self.position = position
        self._day = julian_day
        if raw is not None:
            self._deserialize()

    @property
    def is_broadcast(self):
        return self.height > -2

    @property
    def is_mempool(self):
        return self.height in (-1, 0)

    @property
    def is_confirmed(self):
        return self.height > 0

    @property
    def id(self):
        return self.ref.id

    @property
    def hash(self):
        return self.ref.hash

    def get_julian_day(self, ledger):
        if self._day is None and self.height > 0:
            self._day = ledger.headers.estimated_julian_day(self.height)
        return self._day

    @property
    def raw(self):
        if self._raw is None:
            self._raw = self._serialize()
        return self._raw

    @property
    def raw_sans_segwit(self):
        if self.is_segwit_flag:
            if self._raw_sans_segwit is None:
                self._raw_sans_segwit = self._serialize(sans_segwit=True)
            return self._raw_sans_segwit
        return self.raw

    def _reset(self):
        self._raw = None
        self._raw_sans_segwit = None
        self._raw_outputs = None
        self.ref.reset()

    @property
    def inputs(self) -> ReadOnlyList[Input]:
        return ReadOnlyList(self._inputs)

    @property
    def outputs(self) -> ReadOnlyList[Output]:
        return ReadOnlyList(self._outputs)

    def _add(self, existing_ios: List, new_ios: Iterable[InputOutput], reset=False) -> 'Transaction':
        for txio in new_ios:
            txio.tx_ref = self.ref
            txio.position = len(existing_ios)
            existing_ios.append(txio)
        if reset:
            self._reset()
        return self

    def add_inputs(self, inputs: Iterable[Input]) -> 'Transaction':
        return self._add(self._inputs, inputs, True)

    def add_outputs(self, outputs: Iterable[Output]) -> 'Transaction':
        return self._add(self._outputs, outputs, True)

    @property
    def size(self) -> int:
        """ Size in bytes of the entire transaction. """
        return len(self.raw)

    @property
    def base_size(self) -> int:
        """ Size of transaction without inputs or outputs in bytes. """
        return (
            self.size
            - sum(txi.size for txi in self._inputs)
            - sum(txo.size for txo in self._outputs)
        )

    @property
    def input_sum(self):
        return sum(i.amount for i in self.inputs if i.txo_ref.txo is not None)

    @property
    def output_sum(self):
        return sum(o.amount for o in self.outputs)

    @property
    def net_account_balance(self) -> int:
        balance = 0
        for txi in self.inputs:
            if txi.txo_ref.txo is None:
                continue
            if txi.is_my_input is True:
                balance -= txi.amount
            elif txi.is_my_input is None:
                raise ValueError(
                    "Cannot access net_account_balance if inputs do not "
                    "have is_my_input set properly."
                )
        for txo in self.outputs:
            if txo.is_my_output is True:
                balance += txo.amount
            elif txo.is_my_output is None:
                raise ValueError(
                    "Cannot access net_account_balance if outputs do not "
                    "have is_my_output set properly."
                )
        return balance

    @property
    def fee(self) -> int:
        return self.input_sum - self.output_sum

    def get_base_fee(self, ledger) -> int:
        """ Fee for base tx excluding inputs and outputs. """
        return self.base_size * ledger.fee_per_byte

    def get_effective_input_sum(self, ledger) -> int:
        """ Sum of input values *minus* the cost involved to spend them. """
        return sum(txi.amount - txi.get_fee(ledger) for txi in self._inputs)

    def get_total_output_sum(self, ledger) -> int:
        """ Sum of output values *plus* the cost involved to spend them. """
        return sum(txo.amount + txo.get_fee(ledger) for txo in self._outputs)

    def _serialize(self, with_inputs: bool = True, sans_segwit: bool = False) -> bytes:
        stream = BCDataStream()
        stream.write_uint32(self.version)
        if with_inputs:
            stream.write_compact_size(len(self._inputs))
            for txin in self._inputs:
                txin.serialize_to(stream)
        self._serialize_outputs(stream)
        stream.write_uint32(self.locktime)
        return stream.get_bytes()

    def _serialize_for_signature(self, signing_input: int) -> bytes:
        stream = BCDataStream()
        stream.write_uint32(self.version)
        stream.write_compact_size(len(self._inputs))
        for i, txin in enumerate(self._inputs):
            if signing_input == i:
                assert txin.txo_ref.txo is not None
                txin.serialize_to(stream, txin.txo_ref.txo.script.source)
            else:
                txin.serialize_to(stream, b'')
        self._serialize_outputs(stream)
        stream.write_uint32(self.locktime)
        stream.write_uint32(self.signature_hash_type(1))  # signature hash type: SIGHASH_ALL
        return stream.get_bytes()

    def _serialize_outputs(self, stream):
        if self._raw_outputs is None:
            self._raw_outputs = BCDataStream()
            self._raw_outputs.write_compact_size(len(self._outputs))
            for txout in self._outputs:
                txout.serialize_to(self._raw_outputs)
        stream.write(self._raw_outputs.get_bytes())

    def _deserialize(self):
        if self._raw is not None:
            stream = BCDataStream(self._raw)
            self.version = stream.read_uint32()
            input_count = stream.read_compact_size()
            if input_count == 0:
                self.is_segwit_flag = stream.read_uint8()
                input_count = stream.read_compact_size()
            self._add(self._inputs, [
                Input.deserialize_from(stream) for _ in range(input_count)
            ])
            output_count = stream.read_compact_size()
            self._add(self._outputs, [
                Output.deserialize_from(stream) for _ in range(output_count)
            ])
            if self.is_segwit_flag:
                # drain witness portion of transaction
                # too many witnesses for no crime
                self.witnesses = []
                for _ in range(input_count):
                    for _ in range(stream.read_compact_size()):
                        self.witnesses.append(stream.read(stream.read_compact_size()))
            self.locktime = stream.read_uint32()

    @classmethod
    def ensure_all_have_same_ledger_and_wallet(
            cls, funding_accounts: Iterable['Account'],
            change_account: 'Account' = None) -> Tuple['Ledger', 'Wallet']:
        ledger = wallet = None
        for account in funding_accounts:
            if ledger is None:
                ledger = account.ledger
                wallet = account.wallet
            if ledger != account.ledger:
                raise ValueError(
                    'All funding accounts used to create a transaction must be on the same ledger.'
                )
            if wallet != account.wallet:
                raise ValueError(
                    'All funding accounts used to create a transaction must be from the same wallet.'
                )
        if change_account is not None:
            if change_account.ledger != ledger:
                raise ValueError('Change account must use same ledger as funding accounts.')
            if change_account.wallet != wallet:
                raise ValueError('Change account must use same wallet as funding accounts.')
        if ledger is None:
            raise ValueError('No ledger found.')
        if wallet is None:
            raise ValueError('No wallet found.')
        return ledger, wallet

    @classmethod
    async def create(cls, inputs: Iterable[Input], outputs: Iterable[Output],
                     funding_accounts: Iterable['Account'], change_account: 'Account',
                     sign: bool = True):
        """ Find optimal set of inputs when only outputs are provided; add change
            outputs if only inputs are provided or if inputs are greater than outputs. """

        tx = cls() \
            .add_inputs(inputs) \
            .add_outputs(outputs)

        ledger, _ = cls.ensure_all_have_same_ledger_and_wallet(funding_accounts, change_account)

        # value of the outputs plus associated fees
        cost = (
            tx.get_base_fee(ledger) +
            tx.get_total_output_sum(ledger)
        )
        # value of the inputs less the cost to spend those inputs
        payment = tx.get_effective_input_sum(ledger)

        try:

            for _ in range(5):

                if payment < cost:
                    deficit = cost - payment
                    spendables = await ledger.get_spendable_utxos(deficit, funding_accounts)
                    if not spendables:
                        raise InsufficientFundsError()
                    payment += sum(s.effective_amount for s in spendables)
                    tx.add_inputs(s.txi for s in spendables)

                cost_of_change = (
                    tx.get_base_fee(ledger) +
                    Output.pay_pubkey_hash(COIN, NULL_HASH32).get_fee(ledger)
                )
                if payment > cost:
                    change = payment - cost
                    if change > cost_of_change and change > DUST:
                        change_address = await change_account.change.get_or_create_usable_address()
                        change_hash160 = change_account.ledger.address_to_hash160(change_address)
                        change_amount = change - cost_of_change
                        change_output = Output.pay_pubkey_hash(change_amount, change_hash160)
                        change_output.is_internal_transfer = True
                        tx.add_outputs([Output.pay_pubkey_hash(change_amount, change_hash160)])

                if tx._outputs:
                    break
                # this condition and the outer range(5) loop cover an edge case
                # whereby a single input is just enough to cover the fee and
                # has some change left over, but the change left over is less
                # than the cost_of_change: thus the input is completely
                # consumed and no output is added, which is an invalid tx.
                # to be able to spend this input we must increase the cost
                # of the TX and run through the balance algorithm a second time
                # adding an extra input and change output, making tx valid.
                # we do this 5 times in case the other UTXOs added are also
                # less than the fee, after 5 attempts we give up and go home
                cost += cost_of_change + 1

            if sign:
                await tx.sign(funding_accounts)

        except Exception as e:
            log.exception('Failed to create transaction:')
            await ledger.release_tx(tx)
            raise e

        return tx

    @staticmethod
    def signature_hash_type(hash_type):
        return hash_type

    async def sign(self, funding_accounts: Iterable['Account']):
        self._reset()
        ledger, wallet = self.ensure_all_have_same_ledger_and_wallet(funding_accounts)
        for i, txi in enumerate(self._inputs):
            assert txi.script is not None
            assert txi.txo_ref.txo is not None
            txo_script = txi.txo_ref.txo.script
            if txo_script.is_pay_pubkey_hash:
                address = ledger.hash160_to_address(txo_script.values['pubkey_hash'])
                private_key = await ledger.get_private_key_for_address(wallet, address)
                assert private_key is not None, 'Cannot find private key for signing output.'
                tx = self._serialize_for_signature(i)
                txi.script.values['signature'] = \
                    private_key.sign(tx) + bytes((self.signature_hash_type(1),))
                txi.script.values['pubkey'] = private_key.public_key.pubkey_bytes
                txi.script.generate()
            else:
                raise NotImplementedError("Don't know how to spend this output.")
        self._reset()

    @classmethod
    def pay(cls, amount: int, address: bytes, funding_accounts: List['Account'], change_account: 'Account'):
        ledger, _ = cls.ensure_all_have_same_ledger_and_wallet(funding_accounts, change_account)
        output = Output.pay_pubkey_hash(amount, ledger.address_to_hash160(address))
        return cls.create([], [output], funding_accounts, change_account)

    @classmethod
    def claim_create(
            cls, name: str, claim: Claim, amount: int, holding_address: str,
            funding_accounts: List['Account'], change_account: 'Account', signing_channel: Output = None):
        ledger, _ = cls.ensure_all_have_same_ledger_and_wallet(funding_accounts, change_account)
        claim_output = Output.pay_claim_name_pubkey_hash(
            amount, name, claim, ledger.address_to_hash160(holding_address)
        )
        if signing_channel is not None:
            claim_output.sign(signing_channel, b'placeholder txid:nout')
        return cls.create([], [claim_output], funding_accounts, change_account, sign=False)

    @classmethod
    def claim_update(
            cls, previous_claim: Output, claim: Claim, amount: int, holding_address: str,
            funding_accounts: List['Account'], change_account: 'Account', signing_channel: Output = None):
        ledger, _ = cls.ensure_all_have_same_ledger_and_wallet(funding_accounts, change_account)
        updated_claim = Output.pay_update_claim_pubkey_hash(
            amount, previous_claim.claim_name, previous_claim.claim_id,
            claim, ledger.address_to_hash160(holding_address)
        )
        if signing_channel is not None:
            updated_claim.sign(signing_channel, b'placeholder txid:nout')
        else:
            updated_claim.clear_signature()
        return cls.create(
            [Input.spend(previous_claim)], [updated_claim], funding_accounts, change_account, sign=False
        )

    @classmethod
    def support(cls, claim_name: str, claim_id: str, amount: int, holding_address: str,
                funding_accounts: List['Account'], change_account: 'Account', signing_channel: Output = None,
                comment: str = None):
        ledger, _ = cls.ensure_all_have_same_ledger_and_wallet(funding_accounts, change_account)
        if signing_channel is not None or comment is not None:
            support = Support()
            if comment is not None:
                support.comment = comment
            support_output = Output.pay_support_data_pubkey_hash(
                amount, claim_name, claim_id, support, ledger.address_to_hash160(holding_address)
            )
            if signing_channel is not None:
                support_output.sign(signing_channel, b'placeholder txid:nout')
        else:
            support_output = Output.pay_support_pubkey_hash(
                amount, claim_name, claim_id, ledger.address_to_hash160(holding_address)
            )
        return cls.create([], [support_output], funding_accounts, change_account, sign=False)

    @classmethod
    def purchase(cls, claim_id: str, amount: int, merchant_address: bytes,
                 funding_accounts: List['Account'], change_account: 'Account'):
        ledger, _ = cls.ensure_all_have_same_ledger_and_wallet(funding_accounts, change_account)
        payment = Output.pay_pubkey_hash(amount, ledger.address_to_hash160(merchant_address))
        data = Output.add_purchase_data(Purchase(claim_id))
        return cls.create([], [payment, data], funding_accounts, change_account)

    @property
    def my_inputs(self):
        for txi in self.inputs:
            if txi.txo_ref.txo is not None and txi.txo_ref.txo.is_my_output:
                yield txi

    def _filter_my_outputs(self, f):
        for txo in self.outputs:
            if txo.is_my_output and f(txo.script):
                yield txo

    def _filter_other_outputs(self, f):
        for txo in self.outputs:
            if not txo.is_my_output and f(txo.script):
                yield txo

    def _filter_any_outputs(self, f):
        for txo in self.outputs:
            if f(txo):
                yield txo

    @property
    def my_claim_outputs(self):
        return self._filter_my_outputs(lambda s: s.is_claim_name)

    @property
    def my_update_outputs(self):
        return self._filter_my_outputs(lambda s: s.is_update_claim)

    @property
    def my_support_outputs(self):
        return self._filter_my_outputs(lambda s: s.is_support_claim)

    @property
    def any_purchase_outputs(self):
        return self._filter_any_outputs(lambda o: o.purchase is not None)

    @property
    def other_support_outputs(self):
        return self._filter_other_outputs(lambda s: s.is_support_claim)

    @property
    def my_abandon_outputs(self):
        for txi in self.inputs:
            abandon = txi.txo_ref.txo
            if abandon is not None and abandon.is_my_output and abandon.script.is_claim_involved:
                is_update = False
                if abandon.script.is_claim_name or abandon.script.is_update_claim:
                    for update in self.my_update_outputs:
                        if abandon.claim_id == update.claim_id:
                            is_update = True
                            break
                if not is_update:
                    yield abandon
