import logging
from decimal import Decimal
from binascii import hexlify
from datetime import datetime
from json import JSONEncoder

from google.protobuf.message import DecodeError

from lbrynet.schema.claim import Claim
from lbrynet.wallet.ledger import MainNetLedger, Account
from lbrynet.wallet.transaction import Transaction, Output
from lbrynet.wallet.dewies import dewies_to_lbc
from lbrynet.stream.managed_stream import ManagedStream


log = logging.getLogger(__name__)


def encode_txo_doc():
    return {
        'txid': "hash of transaction in hex",
        'nout': "position in the transaction",
        'height': "block where transaction was recorded",
        'amount': "value of the txo as a decimal",
        'address': "address of who can spend the txo",
        'confirmations': "number of confirmed blocks",
        'is_change': "payment to change address, only available when it can be determined",
        'is_mine': "payment to one of your accounts, only available when it can be determined",
        'type': "one of 'claim', 'support' or 'payment'",
        'name': "when type is 'claim' or 'support', this is the claim name",
        'claim_id': "when type is 'claim' or 'support', this is the claim id",
        'claim_op': "when type is 'claim', this determines if it is 'create' or 'update'",
        'value': "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
        'value_type': "determines the type of the 'value' field: 'channel', 'stream', etc",
        'protobuf': "hex encoded raw protobuf version of 'value' field",
        'permanent_url': "when type is 'claim' or 'support', this is the long permanent claim URL",
        'signing_channel': "for signed claims only, metadata of signing channel",
        'is_channel_signature_valid': "for signed claims only, whether signature is valid",
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
        'streaming_url': '(str) url to stream the file using range requests',
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

    def __init__(self, *args, ledger: MainNetLedger, include_protobuf=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledger = ledger
        self.include_protobuf = include_protobuf

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
            return self.encode_claim(obj)
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
            'height': tx_height,
            'amount': dewies_to_lbc(txo.amount),
            'address': txo.get_address(self.ledger),
            'confirmations': (best_height+1) - tx_height if tx_height > 0 else tx_height,
            'timestamp': self.ledger.headers[tx_height]['timestamp'] if tx_height > 0 else None
        }
        if txo.is_change is not None:
            output['is_change'] = txo.is_change
        if txo.is_my_account is not None:
            output['is_mine'] = txo.is_my_account

        if txo.script.is_claim_name:
            output['type'] = 'claim'
            output['claim_op'] = 'create'
        elif txo.script.is_update_claim:
            output['type'] = 'claim'
            output['claim_op'] = 'update'
        elif txo.script.is_support_claim:
            output['type'] = 'support'
        else:
            output['type'] = 'payment'

        if txo.script.is_claim_involved:
            output.update({
                'name': txo.claim_name,
                'normalized': txo.normalized_name,
                'claim_id': txo.claim_id,
                'permanent_url': txo.permanent_url,
                'meta': self.encode_claim_meta(txo.meta)
            })
            if txo.script.is_claim_name or txo.script.is_update_claim:
                try:
                    output['value'] = txo.claim
                    output['value_type'] = txo.claim.claim_type
                    if self.include_protobuf:
                        output['protobuf'] = hexlify(txo.claim.to_bytes())
                    if txo.channel is not None:
                        output['signing_channel'] = txo.channel
                        if check_signature and txo.claim.is_signed:
                            output['is_channel_signature_valid'] = False
                            if txo.channel:
                                output['is_channel_signature_valid'] = txo.is_signed_by(txo.channel, self.ledger)
                except DecodeError:
                    pass
        return output

    def encode_claim_meta(self, meta):
        if isinstance(meta.get('effective_amount'), int):
            meta['effective_amount'] = dewies_to_lbc(meta['effective_amount'])
        if isinstance(meta.get('trending_amount'), int):
            meta['trending_amount'] = dewies_to_lbc(meta['trending_amount'])
        return meta

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

    def encode_file(self, managed_stream):
        file = managed_stream.as_dict()
        tx_height = managed_stream.stream_claim_info.height
        best_height = self.ledger.headers.height
        file.update({
            'height': tx_height,
            'confirmations': (best_height+1) - tx_height if tx_height > 0 else tx_height,
            'timestamp': self.ledger.headers[tx_height]['timestamp'] if tx_height > 0 else None
        })
        return file

    @staticmethod
    def encode_claim(claim):
        return getattr(claim, claim.claim_type).to_dict()
