import io
import logging
from binascii import hexlify
from typing import List

from lbrynet.wallet import get_wallet_manager
from lbrynet.wallet.bcd_data_stream import BCDataStream
from lbrynet.wallet.hash import sha256, hash160_to_address, claim_id_hash
from lbrynet.wallet.script import InputScript, OutputScript
from lbrynet.wallet.wallet import Wallet


log = logging.getLogger()


NULL_HASH = '\x00'*32


class InputOutput(object):

    @property
    def fee(self):
        """ Fee based on size of the input / output. """
        return get_wallet_manager().fee_per_byte * self.size

    @property
    def size(self):
        """ Size of this input / output in bytes. """
        stream = BCDataStream()
        self.serialize_to(stream)
        return len(stream.get_bytes())

    def serialize_to(self, stream):
        raise NotImplemented


class Input(InputOutput):

    NULL_SIGNATURE = '0'*72
    NULL_PUBLIC_KEY = '0'*33

    def __init__(self, output_or_txid_index, script, sequence=0xFFFFFFFF):
        if isinstance(output_or_txid_index, Output):
            self.output = output_or_txid_index  # type: Output
            self.output_txid = self.output.transaction.id
            self.output_index = self.output.index
        else:
            self.output = None  # type: Output
            self.output_txid, self.output_index = output_or_txid_index
        self.sequence = sequence
        self.is_coinbase = self.output_txid == NULL_HASH
        self.coinbase = script if self.is_coinbase else None
        self.script = script if not self.is_coinbase else None  # type: InputScript

    def link_output(self, output):
        assert self.output is None
        assert self.output_txid == output.transaction.id
        assert self.output_index == output.index
        self.output = output

    @property
    def amount(self):
        """ Amount this input adds to the transaction. """
        if self.output is None:
            raise ValueError('Cannot get input value without referenced output.')
        return self.output.amount

    @property
    def effective_amount(self):
        """ Amount minus fee. """
        return self.amount - self.fee

    def __lt__(self, other):
        return self.effective_amount < other.effective_amount

    @classmethod
    def deserialize_from(cls, stream):
        txid = stream.read(32)
        index = stream.read_uint32()
        script = stream.read_string()
        sequence = stream.read_uint32()
        return cls(
            (txid, index),
            InputScript(script) if not txid == NULL_HASH else script,
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

    def to_python_source(self):
        return (
            u"InputScript(\n"
            u"    (output_txid=unhexlify('{}'), output_index={}),\n"
            u"    script=unhexlify('{}')\n"
            u"    # tokens: {}\n"
            u")").format(
                hexlify(self.output_txid), self.output_index,
                hexlify(self.coinbase) if self.is_coinbase else hexlify(self.script.source),
                repr(self.script.tokens)
            )


class Output(InputOutput):

    def __init__(self, transaction, index, amount, script):
        self.transaction = transaction  # type: Transaction
        self.index = index  # type: int
        self.amount = amount  # type: int
        self.script = script  # type: OutputScript
        self._effective_amount = None  # type: int

    def __lt__(self, other):
        return self.effective_amount < other.effective_amount

    def _add_and_return(self):
        self.transaction.add_outputs([self])
        return self

    @classmethod
    def pay_pubkey_hash(cls, transaction, index, amount, pubkey_hash):
        return cls(
            transaction, index, amount,
            OutputScript.pay_pubkey_hash(pubkey_hash)
        )._add_and_return()

    @classmethod
    def pay_claim_name_pubkey_hash(cls, transaction, index, amount, claim_name, claim, pubkey_hash):
        return cls(
            transaction, index, amount,
            OutputScript.pay_claim_name_pubkey_hash(claim_name, claim, pubkey_hash)
        )._add_and_return()

    def spend(self, signature=Input.NULL_SIGNATURE, pubkey=Input.NULL_PUBLIC_KEY):
        """ Create the input to spend this output."""
        assert self.script.is_pay_pubkey_hash, 'Attempting to spend unsupported output.'
        script = InputScript.redeem_pubkey_hash(signature, pubkey)
        return Input(self, script)

    @property
    def effective_amount(self):
        """ Amount minus fees it would take to spend this output. """
        if self._effective_amount is None:
            txi = self.spend()
            self._effective_amount = txi.effective_amount
        return self._effective_amount

    @classmethod
    def deserialize_from(cls, stream, transaction, index):
        return cls(
            transaction=transaction,
            index=index,
            amount=stream.read_uint64(),
            script=OutputScript(stream.read_string())
        )

    def serialize_to(self, stream):
        stream.write_uint64(self.amount)
        stream.write_string(self.script.source)

    def to_python_source(self):
        return (
            u"OutputScript(tx, index={}, amount={},\n"
            u"    script=unhexlify('{}')\n"
            u"    # tokens: {}\n"
            u")").format(
            self.index, self.amount, hexlify(self.script.source), repr(self.script.tokens))


class Transaction:

    def __init__(self, raw=None, version=1, locktime=0, height=None, is_saved=False):
        self._raw = raw
        self._hash = None
        self._id = None
        self.version = version  # type: int
        self.locktime = locktime  # type: int
        self.height = height  # type: int
        self.inputs = []  # type: List[Input]
        self.outputs = []  # type: List[Output]
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
        self._raw = None
        self._hash = None
        self._id = None

    def get_claim_id(self, output_index):
        script = self.outputs[output_index]
        assert script.script.is_claim_name(), 'Not a name claim.'
        return claim_id_hash(self.hash, output_index)

    @property
    def is_complete(self):
        s, r = self.signature_count()
        return r == s

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

    @property
    def base_fee(self):
        """ Fee for the transaction header and all outputs; without inputs. """
        byte_fee = get_wallet_manager().fee_per_byte * self.base_size
        return max(byte_fee, self.claim_name_fee)

    @property
    def claim_name_fee(self):
        char_fee = get_wallet_manager().fee_per_name_char
        fee = 0
        for output in self.outputs:
            if output.script.is_claim_name:
                fee += len(output.script.values['claim_name']) * char_fee
        return fee

    def _serialize(self, with_inputs=True):
        stream = BCDataStream()
        stream.write_uint32(self.version)
        if with_inputs:
            stream.write_compact_size(len(self.inputs))
            for txin in self.inputs:
                txin.serialize_to(stream)
        stream.write_compact_size(len(self.outputs))
        for txout in self.outputs:
            txout.serialize_to(stream)
        stream.write_uint32(self.locktime)
        return stream.get_bytes()

    def _serialize_for_signature(self, signing_input):
        stream = BCDataStream()
        stream.write_uint32(self.version)
        stream.write_compact_size(len(self.inputs))
        for i, txin in enumerate(self.inputs):
            if signing_input == i:
                txin.serialize_to(stream, txin.output.script.source)
            else:
                txin.serialize_to(stream, b'')
        stream.write_compact_size(len(self.outputs))
        for txout in self.outputs:
            txout.serialize_to(stream)
        stream.write_uint32(self.locktime)
        stream.write_uint32(1)  # signature hash type: SIGHASH_ALL
        return stream.get_bytes()

    def _deserialize(self):
        if self._raw is not None:
            stream = BCDataStream(self._raw)
            self.version = stream.read_uint32()
            input_count = stream.read_compact_size()
            self.inputs = [Input.deserialize_from(stream) for _ in range(input_count)]
            output_count = stream.read_compact_size()
            self.outputs = [Output.deserialize_from(stream, self, i) for i in range(output_count)]
            self.locktime = stream.read_uint32()

    def add_inputs(self, inputs):
        self.inputs.extend(inputs)
        self._reset()

    def add_outputs(self, outputs):
        self.outputs.extend(outputs)
        self._reset()

    def sign(self, wallet):  # type: (Wallet) -> bool
        for i, txi in enumerate(self.inputs):
            txo_script = txi.output.script
            if txo_script.is_pay_pubkey_hash:
                address = hash160_to_address(txo_script.values['pubkey_hash'], wallet.chain)
                private_key = wallet.get_private_key_for_address(address)
                tx = self._serialize_for_signature(i)
                txi.script.values['signature'] = private_key.sign(tx)
                txi.script.values['pubkey'] = private_key.public_key.pubkey_bytes
                txi.script.generate()
        self._reset()
        return True

    def sort(self):
        # See https://github.com/kristovatlas/rfc/blob/master/bips/bip-li01.mediawiki
        self.inputs.sort(key=lambda i: (i['prevout_hash'], i['prevout_n']))
        self.outputs.sort(key=lambda o: (o[2], pay_script(o[0], o[1])))

    @property
    def input_sum(self):
        return sum(i.amount for i in self.inputs)

    @property
    def output_sum(self):
        return sum(o.amount for o in self.outputs)

    def to_python_source(self):
        s = io.StringIO()
        s.write(u'tx = Transaction(version={}, locktime={}, height={})\n'.format(
            self.version, self.locktime, self.height
        ))
        for txi in self.inputs:
            s.write(u'tx.add_input(')
            s.write(txi.to_python_source())
            s.write(u')\n')
        for txo in self.outputs:
            s.write(u'tx.add_output(')
            s.write(txo.to_python_source())
            s.write(u')\n')
        s.write(u'# tx.id: unhexlify("{}")\n'.format(hexlify(self.id)))
        s.write(u'# tx.raw: unhexlify("{}")\n'.format(hexlify(self.raw)))
        return s.getvalue()
