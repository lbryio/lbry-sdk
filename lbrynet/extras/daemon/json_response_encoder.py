import logging
from decimal import Decimal
from binascii import hexlify
from datetime import datetime
from json import JSONEncoder
from ecdsa import BadSignatureError
from lbrynet.schema.claim import Claim
from lbrynet.wallet.ledger import MainNetLedger
from lbrynet.wallet.transaction import Transaction, Output
from lbrynet.wallet.dewies import dewies_to_lbc


log = logging.getLogger(__name__)


class JSONResponseEncoder(JSONEncoder):

    def __init__(self, *args, ledger: MainNetLedger, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledger = ledger

    def default(self, obj):  # pylint: disable=method-hidden
        if isinstance(obj, Transaction):
            return self.encode_transaction(obj)
        if isinstance(obj, Output):
            return self.encode_output(obj)
        if isinstance(obj, Claim):
            claim_dict = obj.to_dict()
            if obj.is_stream:
                claim_dict['stream']['hash'] = obj.stream.hash
            return claim_dict
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

    def encode_output(self, txo, check_signature=True):
        tx_height = txo.tx_ref.height
        best_height = self.ledger.headers.height
        output = {
            'txid': txo.tx_ref.id,
            'nout': txo.position,
            'amount': dewies_to_lbc(txo.amount),
            'address': txo.get_address(self.ledger),
            'height': tx_height,
            'confirmations': (best_height+1) - tx_height if tx_height > 0 else tx_height
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
            })

            if txo.script.is_claim_name or txo.script.is_update_claim:
                claim = txo.claim
                output['value'] = claim
                if claim.is_signed:
                    output['valid_signature'] = None
                    if check_signature and txo.channel is not None:
                        output['channel_name'] = txo.channel.claim_name
                        try:
                            output['valid_signature'] = txo.is_signed_by(txo.channel, self.ledger)
                        except BadSignatureError:
                            output['valid_signature'] = False
                        except ValueError:
                            log.exception(
                                'txo.id: %s, txo.channel.id:%s, output: %s',
                                txo.id, txo.channel.id, output
                            )
                            output['valid_signature'] = False

            if txo.script.is_claim_name:
                output['type'] = 'claim'
            elif txo.script.is_update_claim:
                output['type'] = 'update'
            elif txo.script.is_support_claim:
                output['type'] = 'support'
            else:
                output['type'] = 'basic'

        return output

    def encode_input(self, txi):
        return self.encode_output(txi.txo_ref.txo, False) if txi.txo_ref.txo is not None else {
            'txid': txi.txo_ref.tx_ref.id,
            'nout': txi.txo_ref.position
        }
