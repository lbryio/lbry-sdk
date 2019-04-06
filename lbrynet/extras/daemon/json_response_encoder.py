import logging
from decimal import Decimal
from binascii import hexlify
from datetime import datetime
from json import JSONEncoder
from ecdsa import BadSignatureError
from lbrynet.schema.claim import Claim
from lbrynet.wallet.ledger import MainNetLedger, Account
from lbrynet.wallet.transaction import Transaction, Output
from lbrynet.wallet.dewies import dewies_to_lbc
from lbrynet.stream.managed_stream import ManagedStream


log = logging.getLogger(__name__)


def encode_txo_doc():
    return {
        'txid': "hash of transaction in hex",
        'height': "block where transaction was recorded",
        'nout': "position in the transaction",
        'amount': "value of the txo as a decimal",
        'address': "address of who can spend the txo",
        'confirmations': "number of confirmed blocks"
    }


def encode_tx_doc():
    return {
        'txid': "hash of transaction in hex",
        'height': "block where transaction was recorded",
        'inputs': [encode_txo_doc()],
        'outputs': [encode_txo_doc()],
        'total_input': "sum of inputs as a decimal",
        'total_output': "sum of outputs, sans fee, as a decimal",
        'total_fee': "fee amount",
        'hex': "entire transaction encoded in hex",
    }


def encode_account_doc():
    return {
        'id': 'account_id',
        'is_default': 'this account is used by default',
        'ledger': 'name of crypto currency and network',
        'name': 'optional account name',
        'seed': 'human friendly words from which account can be recreated',
        'encrypted': 'if account is encrypted',
        'private_key': 'extended private key',
        'public_key': 'extended public key',
        'address_generator': 'settings for generating addresses',
        'modified_on': 'date of last modification to account settings'
    }


def encode_file_doc():
    return {
        'completed': '(bool) true if download is completed',
        'file_name': '(str) name of file',
        'download_directory': '(str) download directory',
        'points_paid': '(float) credit paid to download file',
        'stopped': '(bool) true if download is stopped',
        'stream_hash': '(str) stream hash of file',
        'stream_name': '(str) stream name',
        'suggested_file_name': '(str) suggested file name',
        'sd_hash': '(str) sd hash of file',
        'download_path': '(str) download path of file',
        'mime_type': '(str) mime type of file',
        'key': '(str) key attached to file',
        'total_bytes_lower_bound': '(int) lower bound file size in bytes',
        'total_bytes': '(int) file upper bound size in bytes',
        'written_bytes': '(int) written size in bytes',
        'blobs_completed': '(int) number of fully downloaded blobs',
        'blobs_in_stream': '(int) total blobs on stream',
        'blobs_remaining': '(int) total blobs remaining to download',
        'status': '(str) downloader status',
        'claim_id': '(str) None if claim is not found else the claim id',
        'txid': '(str) None if claim is not found else the transaction id',
        'nout': '(int) None if claim is not found else the transaction output index',
        'outpoint': '(str) None if claim is not found else the tx and output',
        'metadata': '(dict) None if claim is not found else the claim metadata',
        'channel_claim_id': '(str) None if claim is not found or not signed',
        'channel_name': '(str) None if claim is not found or not signed',
        'claim_name': '(str) None if claim is not found else the claim name'
    }


class JSONResponseEncoder(JSONEncoder):

    def __init__(self, *args, ledger: MainNetLedger, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledger = ledger

    def default(self, obj):  # pylint: disable=method-hidden
        if isinstance(obj, Account):
            return self.encode_account(obj)
        if isinstance(obj, ManagedStream):
            return self.encode_file(obj)
        if isinstance(obj, Transaction):
            return self.encode_transaction(obj)
        if isinstance(obj, Output):
            return self.encode_output(obj)
        if isinstance(obj, Claim):
            claim_dict = obj.to_dict()
            if obj.is_stream:
                claim_dict['stream']['sd_hash'] = obj.stream.sd_hash
                fee = claim_dict['stream'].get('fee', {})
                if 'address' in fee:
                    fee['address'] = obj.stream.fee.address
                if 'amount' in fee:
                    fee['amount'] = obj.stream.fee.amount
                if 'languages' in claim_dict['stream']:
                    claim_dict['stream']['languages'] = obj.stream.langtags
            elif obj.is_channel:
                claim_dict['channel']['public_key'] = obj.channel.public_key
                if 'languages' in claim_dict['channel']:
                    claim_dict['channel']['languages'] = obj.channel.langtags
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

    def encode_account(self, account):
        result = account.to_dict()
        result['id'] = account.id
        result.pop('certificates', None)
        result['is_default'] = self.ledger.accounts[0] == account
        return result

    @staticmethod
    def encode_file(managed_stream):
        return managed_stream.as_dict()
