from decimal import Decimal
from binascii import hexlify
from datetime import datetime
from json import JSONEncoder
from lbrynet.wallet.transaction import Transaction, Output
from lbrynet.wallet.dewies import dewies_to_lbc


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
            'height': tx.height,
            'inputs': [self.encode_input(txo) for txo in tx.inputs],
            'outputs': [self.encode_output(txo) for txo in tx.outputs],
            'total_input': dewies_to_lbc(tx.input_sum),
            'total_output': dewies_to_lbc(tx.input_sum - tx.fee),
            'total_fee': dewies_to_lbc(tx.fee),
            'hex': hexlify(tx.raw).decode(),
        }

    def encode_output(self, txo):
        output = {
            'txid': txo.tx_ref.id,
            'nout': txo.position,
            'amount': dewies_to_lbc(txo.amount),
            'address': txo.get_address(self.ledger),
        }
        if txo.is_change is not None:
            output['is_change'] = txo.is_change
        if txo.is_my_account is not None:
            output['is_mine'] = txo.is_my_account
        if txo.script.is_claim_involved:
            output.update({
                'name': txo.claim_name,
                'claim_id': txo.claim_id,
                'permanent_url': txo.permanent_url,
                'is_claim': txo.script.is_claim_name,
                'is_support': txo.script.is_support_claim,
                'is_update': txo.script.is_update_claim
            })
            if txo.script.is_claim_name:
                output.update({
                    'category': 'claim',
                    'value': txo.claim.claim_dict
                })
            elif txo.script.is_update_claim:
                output.update({
                    'category': 'update',
                    'value': txo.claim.claim_dict
                })
            elif txo.script.is_support_claim:
                output['category'] = 'support'
        return output

    def encode_input(self, txi):
        return self.encode_output(txi.txo_ref.txo) if txi.txo_ref.txo is not None else {
            'txid': txi.txo_ref.tx_ref.id,
            'nout': txi.txo_ref.position
        }
