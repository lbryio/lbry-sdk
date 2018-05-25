import six
import logging
from typing import List
from collections import namedtuple

from torba.basecoin import BaseCoin
from torba.basescript import BaseInputScript, BaseOutputScript
from torba.bcd_data_stream import BCDataStream
from torba.hash import sha256
from torba.account import Account
from torba.util import ReadOnlyList


log = logging.getLogger()


NULL_HASH = b'\x00'*32


class InputOutput(object):

    @property
    def size(self):
        """ Size of this input / output in bytes. """
        stream = BCDataStream()
        self.serialize_to(stream)
        return len(stream.get_bytes())

    def serialize_to(self, stream):
        raise NotImplemented


class BaseInput(InputOutput):

    script_class = None

    NULL_SIGNATURE = b'\x00'*72
    NULL_PUBLIC_KEY = b'\x00'*33

    def __init__(self, output_or_txid_index, script, sequence=0xFFFFFFFF):
        if isinstance(output_or_txid_index, BaseOutput):
            self.output = output_or_txid_index  # type: BaseOutput
            self.output_txid = self.output.transaction.hash
            self.output_index = self.output.index
        else:
            self.output = None  # type: BaseOutput
            self.output_txid, self.output_index = output_or_txid_index
        self.sequence = sequence
        self.is_coinbase = self.output_txid == NULL_HASH
        self.coinbase = script if self.is_coinbase else None
        self.script = script if not self.is_coinbase else None  # type: BaseInputScript

    def link_output(self, output):
        assert self.output is None
        assert self.output_txid == output.transaction.hash
        assert self.output_index == output.index
        self.output = output

    @classmethod
    def spend(cls, output):
        """ Create an input to spend the output."""
        assert output.script.is_pay_pubkey_hash, 'Attempting to spend unsupported output.'
        script = cls.script_class.redeem_pubkey_hash(cls.NULL_SIGNATURE, cls.NULL_PUBLIC_KEY)
        return cls(output, script)

    @property
    def amount(self):
        """ Amount this input adds to the transaction. """
        if self.output is None:
            raise ValueError('Cannot get input value without referenced output.')
        return self.output.amount

    @classmethod
    def deserialize_from(cls, stream):
        txid = stream.read(32)
        index = stream.read_uint32()
        script = stream.read_string()
        sequence = stream.read_uint32()
        return cls(
            (txid, index),
            cls.script_class(script) if not txid == NULL_HASH else script,
            sequence
        )

    def serialize_to(self, stream, alternate_script=None):
        stream.write(self.output_txid)
        stream.write_uint32(self.output_index)
        if alternate_script is not None:
            stream.write_string(alternate_script)
        else:
            if self.is_coinbase:
                stream.write_string(self.coinbase)
            else:
                stream.write_string(self.script.source)
        stream.write_uint32(self.sequence)


class BaseOutputAmountEstimator(object):

    __slots__ = 'coin', 'output', 'fee', 'effective_amount'

    def __init__(self, coin, txo):  # type: (BaseCoin, BaseOutput) -> None
        self.coin = coin
        self.output = txo
        txi = coin.transaction_class.input_class.spend(txo)
        self.fee = coin.get_input_output_fee(txi)
        self.effective_amount = txo.amount - self.fee

    def __lt__(self, other):
        return self.effective_amount < other.effective_amount


class BaseOutput(InputOutput):

    script_class = None
    estimator_class = BaseOutputAmountEstimator

    def __init__(self, amount, script):
        self.amount = amount  # type: int
        self.script = script  # type: BaseOutputScript
        self.transaction = None  # type: BaseTransaction
        self.index = None  # type: int

    def get_estimator(self, coin):
        return self.estimator_class(coin, self)

    @classmethod
    def pay_pubkey_hash(cls, amount, pubkey_hash):
        return cls(amount, cls.script_class.pay_pubkey_hash(pubkey_hash))

    @classmethod
    def deserialize_from(cls, stream):
        return cls(
            amount=stream.read_uint64(),
            script=cls.script_class(stream.read_string())
        )

    def serialize_to(self, stream):
        stream.write_uint64(self.amount)
        stream.write_string(self.script.source)


class BaseTransaction:

    input_class = None
    output_class = None

    def __init__(self, raw=None, version=1, locktime=0, height=None, is_saved=False):
        self._raw = raw
        self._hash = None
        self._id = None
        self.version = version  # type: int
        self.locktime = locktime  # type: int
        self.height = height  # type: int
        self._inputs = []  # type: List[BaseInput]
        self._outputs = []  # type: List[BaseOutput]
        self.is_saved = is_saved  # type: bool
        if raw is not None:
            self._deserialize()

    @property
    def id(self):
        if self._id is None:
            self._id = self.hash[::-1]
        return self._id

    @property
    def hash(self):
        if self._hash is None:
            self._hash = sha256(sha256(self.raw))
        return self._hash

    @property
    def raw(self):
        if self._raw is None:
            self._raw = self._serialize()
        return self._raw

    def _reset(self):
        self._id = None
        self._hash = None
        self._raw = None

    @property
    def inputs(self):  # type: () -> ReadOnlyList[BaseInput]
        return ReadOnlyList(self._inputs)

    @property
    def outputs(self):  # type: () -> ReadOnlyList[BaseOutput]
        return ReadOnlyList(self._outputs)

    def add_inputs(self, inputs):
        self._inputs.extend(inputs)
        self._reset()
        return self

    def add_outputs(self, outputs):
        for txo in outputs:
            txo.transaction = self
            txo.index = len(self._outputs)
            self._outputs.append(txo)
        self._reset()
        return self

    @property
    def fee(self):
        """ Fee that will actually be paid."""
        return self.input_sum - self.output_sum

    @property
    def size(self):
        """ Size in bytes of the entire transaction. """
        return len(self.raw)

    @property
    def base_size(self):
        """ Size in bytes of transaction meta data and all outputs; without inputs. """
        return len(self._serialize(with_inputs=False))

    def _serialize(self, with_inputs=True):
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

    def _serialize_for_signature(self, signing_input):
        stream = BCDataStream()
        stream.write_uint32(self.version)
        stream.write_compact_size(len(self._inputs))
        for i, txin in enumerate(self._inputs):
            if signing_input == i:
                txin.serialize_to(stream, txin.output.script.source)
            else:
                txin.serialize_to(stream, b'')
        stream.write_compact_size(len(self._outputs))
        for txout in self._outputs:
            txout.serialize_to(stream)
        stream.write_uint32(self.locktime)
        stream.write_uint32(1)  # signature hash type: SIGHASH_ALL
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

    def sign(self, account):  # type: (Account) -> BaseTransaction
        for i, txi in enumerate(self._inputs):
            txo_script = txi.output.script
            if txo_script.is_pay_pubkey_hash:
                address = account.coin.hash160_to_address(txo_script.values['pubkey_hash'])
                private_key = account.get_private_key_for_address(address)
                tx = self._serialize_for_signature(i)
                txi.script.values['signature'] = private_key.sign(tx)+six.int2byte(1)
                txi.script.values['pubkey'] = private_key.public_key.pubkey_bytes
                txi.script.generate()
        self._reset()
        return self

    def sort(self):
        # See https://github.com/kristovatlas/rfc/blob/master/bips/bip-li01.mediawiki
        self._inputs.sort(key=lambda i: (i['prevout_hash'], i['prevout_n']))
        self._outputs.sort(key=lambda o: (o[2], pay_script(o[0], o[1])))

    @property
    def input_sum(self):
        return sum(i.amount for i in self._inputs)

    @property
    def output_sum(self):
        return sum(o.amount for o in self._outputs)
