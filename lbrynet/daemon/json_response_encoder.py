from decimal import Decimal
from binascii import hexlify
from datetime import datetime
from json import JSONEncoder
from lbrynet.wallet.transaction import Transaction, Output


class JSONResponseEncoder(JSONEncoder):

    def __init__(self, *args, ledger, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledger = ledger

    def default(self, obj):  # pylint: disable=method-hidden
        if isinstance(obj, Transaction):
            return self.encode_transaction(obj)
        if isinstance(obj, Output):
            return self.encode_output(obj)
        if isinstance(obj, datetime):
            return obj.strftime("%Y%m%dT%H:%M:%S")
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, bytes):
            return obj.decode()
        return super().default(obj)

    def encode_transaction(self, tx):
        return {
            'txid': tx.id,
            'inputs': [self.encode_input(txo) for txo in tx.inputs],
            'outputs': [self.encode_output(txo) for txo in tx.outputs],
            'total_input': tx.input_sum,
            'total_output': tx.input_sum - tx.fee,
            'total_fee': tx.fee,
            'hex': hexlify(tx.raw).decode(),
        }

    def encode_output(self, txo):
        return {
            'nout': txo.position,
            'amount': txo.amount,
            'address': txo.get_address(self.ledger)
        }

    def encode_input(self, txi):
        return self.encode_output(txi.txo_ref.txo)
