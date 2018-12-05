import logging
import typing
from typing import List, Iterable, Optional
from binascii import hexlify

from torba.client.basescript import BaseInputScript, BaseOutputScript
from torba.client.baseaccount import BaseAccount
from torba.client.constants import COIN, NULL_HASH32
from torba.client.bcd_data_stream import BCDataStream
from torba.client.hash import sha256, TXRef, TXRefImmutable
from torba.client.util import ReadOnlyList

if typing.TYPE_CHECKING:
    from torba.client import baseledger

log = logging.getLogger()


class TXRefMutable(TXRef):

    __slots__ = ('tx',)

    def __init__(self, tx: 'BaseTransaction') -> None:
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
            self._hash = sha256(sha256(self.tx.raw))
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
        return '{}:{}'.format(self.tx_ref.id, self.position)

    @property
    def is_null(self):
        return self.tx_ref.is_null

    @property
    def txo(self) -> Optional['BaseOutput']:
        return None


class TXORefResolvable(TXORef):

    __slots__ = ('_txo',)

    def __init__(self, txo: 'BaseOutput') -> None:
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


class BaseInput(InputOutput):

    script_class = BaseInputScript

    NULL_SIGNATURE = b'\x00'*72
    NULL_PUBLIC_KEY = b'\x00'*33

    __slots__ = 'txo_ref', 'sequence', 'coinbase', 'script'

    def __init__(self, txo_ref: TXORef, script: BaseInputScript, sequence: int = 0xFFFFFFFF,
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
    def spend(cls, txo: 'BaseOutput') -> 'BaseInput':
        """ Create an input to spend the output."""
        assert txo.script.is_pay_pubkey_hash, 'Attempting to spend unsupported output.'
        script = cls.script_class.redeem_pubkey_hash(cls.NULL_SIGNATURE, cls.NULL_PUBLIC_KEY)
        return cls(txo.ref, script)

    @property
    def amount(self) -> int:
        """ Amount this input adds to the transaction. """
        if self.txo_ref.txo is None:
            raise ValueError('Cannot resolve output to get amount.')
        return self.txo_ref.txo.amount

    @property
    def is_my_account(self) -> Optional[bool]:
        """ True if the output this input spends is yours. """
        if self.txo_ref.txo is None:
            return False
        return self.txo_ref.txo.is_my_account

    @classmethod
    def deserialize_from(cls, stream):
        tx_ref = TXRefImmutable.from_hash(stream.read(32), -1)
        position = stream.read_uint32()
        script = stream.read_string()
        sequence = stream.read_uint32()
        return cls(
            TXORef(tx_ref, position),
            cls.script_class(script) if not tx_ref.is_null else script,
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


class BaseOutputEffectiveAmountEstimator:

    __slots__ = 'txo', 'txi', 'fee', 'effective_amount'

    def __init__(self, ledger: 'baseledger.BaseLedger', txo: 'BaseOutput') -> None:
        self.txo = txo
        self.txi = ledger.transaction_class.input_class.spend(txo)
        self.fee: int = self.txi.get_fee(ledger)
        self.effective_amount: int = txo.amount - self.fee

    def __lt__(self, other):
        return self.effective_amount < other.effective_amount


class BaseOutput(InputOutput):

    script_class = BaseOutputScript
    estimator_class = BaseOutputEffectiveAmountEstimator

    __slots__ = 'amount', 'script', 'is_change', 'is_my_account'

    def __init__(self, amount: int, script: BaseOutputScript,
                 tx_ref: TXRef = None, position: int = None,
                 is_change: Optional[bool] = None, is_my_account: Optional[bool] = None
                 ) -> None:
        super().__init__(tx_ref, position)
        self.amount = amount
        self.script = script
        self.is_change = is_change
        self.is_my_account = is_my_account

    def update_annotations(self, annotated):
        if annotated is None:
            self.is_change = False
            self.is_my_account = False
        else:
            self.is_change = annotated.is_change
            self.is_my_account = annotated.is_my_account

    @property
    def ref(self):
        return TXORefResolvable(self)

    @property
    def id(self):
        return self.ref.id

    def get_address(self, ledger):
        return ledger.hash160_to_address(
            self.script.values['pubkey_hash']
        )

    def get_estimator(self, ledger):
        return self.estimator_class(ledger, self)

    @classmethod
    def pay_pubkey_hash(cls, amount, pubkey_hash):
        return cls(amount, cls.script_class.pay_pubkey_hash(pubkey_hash))

    @classmethod
    def deserialize_from(cls, stream):
        return cls(
            amount=stream.read_uint64(),
            script=cls.script_class(stream.read_string())
        )

    def serialize_to(self, stream, alternate_script=None):
        stream.write_uint64(self.amount)
        stream.write_string(self.script.source)


class BaseTransaction:

    input_class = BaseInput
    output_class = BaseOutput

    def __init__(self, raw=None, version: int = 1, locktime: int = 0, is_verified: bool = False,
                 height: int = -2, position: int = -1) -> None:
        self._raw = raw
        self.ref = TXRefMutable(self)
        self.version = version
        self.locktime = locktime
        self._inputs: List[BaseInput] = []
        self._outputs: List[BaseOutput] = []
        self.is_verified = is_verified
        # Height Progression
        #   -2: not broadcast
        #   -1: in mempool but has unconfirmed inputs
        #    0: in mempool and all inputs confirmed
        # +num: confirmed in a specific block (height)
        self.height = height
        self.position = position
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

    @property
    def raw(self):
        if self._raw is None:
            self._raw = self._serialize()
        return self._raw

    def _reset(self):
        self._raw = None
        self.ref.reset()

    @property
    def inputs(self) -> ReadOnlyList[BaseInput]:
        return ReadOnlyList(self._inputs)

    @property
    def outputs(self) -> ReadOnlyList[BaseOutput]:
        return ReadOnlyList(self._outputs)

    def _add(self, new_ios: Iterable[InputOutput], existing_ios: List) -> 'BaseTransaction':
        for txio in new_ios:
            txio.tx_ref = self.ref
            txio.position = len(existing_ios)
            existing_ios.append(txio)
        self._reset()
        return self

    def add_inputs(self, inputs: Iterable[BaseInput]) -> 'BaseTransaction':
        return self._add(inputs, self._inputs)

    def add_outputs(self, outputs: Iterable[BaseOutput]) -> 'BaseTransaction':
        return self._add(outputs, self._outputs)

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
            if txi.is_my_account is None:
                raise ValueError(
                    "Cannot access net_account_balance if inputs/outputs do not "
                    "have is_my_account set properly."
                )
            elif txi.is_my_account:
                balance -= txi.amount
        for txo in self.outputs:
            if txo.is_my_account is None:
                raise ValueError(
                    "Cannot access net_account_balance if inputs/outputs do not "
                    "have is_my_account set properly."
                )
            elif txo.is_my_account:
                balance += txo.amount
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

    def _serialize(self, with_inputs: bool = True) -> bytes:
        stream = BCDataStream()
        stream.write_uint32(self.version)
        if with_inputs:
            stream.write_compact_size(len(self._inputs))
            for txin in self._inputs:
                txin.serialize_to(stream)
        stream.write_compact_size(len(self._outputs))
        for txout in self._outputs:
            txout.serialize_to(stream)
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
        stream.write_compact_size(len(self._outputs))
        for txout in self._outputs:
            txout.serialize_to(stream)
        stream.write_uint32(self.locktime)
        stream.write_uint32(self.signature_hash_type(1))  # signature hash type: SIGHASH_ALL
        return stream.get_bytes()

    def _deserialize(self):
        if self._raw is not None:
            stream = BCDataStream(self._raw)
            self.version = stream.read_uint32()
            input_count = stream.read_compact_size()
            self.add_inputs([
                self.input_class.deserialize_from(stream) for _ in range(input_count)
            ])
            output_count = stream.read_compact_size()
            self.add_outputs([
                self.output_class.deserialize_from(stream) for _ in range(output_count)
            ])
            self.locktime = stream.read_uint32()

    @classmethod
    def ensure_all_have_same_ledger(cls, funding_accounts: Iterable[BaseAccount],
                                    change_account: BaseAccount = None) -> 'baseledger.BaseLedger':
        ledger = None
        for account in funding_accounts:
            if ledger is None:
                ledger = account.ledger
            if ledger != account.ledger:
                raise ValueError(
                    'All funding accounts used to create a transaction must be on the same ledger.'
                )
        if change_account is not None and change_account.ledger != ledger:
            raise ValueError('Change account must use same ledger as funding accounts.')
        if ledger is None:
            raise ValueError('No ledger found.')
        return ledger

    @classmethod
    async def create(cls, inputs: Iterable[BaseInput], outputs: Iterable[BaseOutput],
                     funding_accounts: Iterable[BaseAccount], change_account: BaseAccount):
        """ Find optimal set of inputs when only outputs are provided; add change
            outputs if only inputs are provided or if inputs are greater than outputs. """

        tx = cls() \
            .add_inputs(inputs) \
            .add_outputs(outputs)

        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)

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
                        raise ValueError('Not enough funds to cover this transaction.')
                    payment += sum(s.effective_amount for s in spendables)
                    tx.add_inputs(s.txi for s in spendables)

                cost_of_change = (
                    tx.get_base_fee(ledger) +
                    cls.output_class.pay_pubkey_hash(COIN, NULL_HASH32).get_fee(ledger)
                )
                if payment > cost:
                    change = payment - cost
                    if change > cost_of_change:
                        change_address = await change_account.change.get_or_create_usable_address()
                        change_hash160 = change_account.ledger.address_to_hash160(change_address)
                        change_amount = change - cost_of_change
                        change_output = cls.output_class.pay_pubkey_hash(change_amount, change_hash160)
                        change_output.is_change = True
                        tx.add_outputs([cls.output_class.pay_pubkey_hash(change_amount, change_hash160)])

                if tx._outputs:
                    break
                else:
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

            await tx.sign(funding_accounts)

        except Exception as e:
            log.exception('Failed to create transaction:')
            await ledger.release_outputs(tx.outputs)
            raise e

        return tx

    @staticmethod
    def signature_hash_type(hash_type):
        return hash_type

    async def sign(self, funding_accounts: Iterable[BaseAccount]):
        ledger = self.ensure_all_have_same_ledger(funding_accounts)
        for i, txi in enumerate(self._inputs):
            assert txi.script is not None
            assert txi.txo_ref.txo is not None
            txo_script = txi.txo_ref.txo.script
            if txo_script.is_pay_pubkey_hash:
                address = ledger.hash160_to_address(txo_script.values['pubkey_hash'])
                private_key = await ledger.get_private_key_for_address(address)
                tx = self._serialize_for_signature(i)
                txi.script.values['signature'] = \
                    private_key.sign(tx) + bytes((self.signature_hash_type(1),))
                txi.script.values['pubkey'] = private_key.public_key.pubkey_bytes
                txi.script.generate()
            else:
                raise NotImplementedError("Don't know how to spend this output.")
        self._reset()
