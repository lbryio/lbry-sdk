import logging
from decimal import Decimal
from binascii import hexlify, unhexlify
from datetime import datetime
from json import JSONEncoder

from google.protobuf.message import DecodeError

from lbry.schema.claim import Claim
from lbry.torrent.torrent_manager import TorrentSource
from lbry.wallet import Wallet, Ledger, Account, Transaction, Output
from lbry.wallet.bip32 import PubKey
from lbry.wallet.dewies import dewies_to_lbc
from lbry.stream.managed_stream import ManagedStream


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
        'is_received': "true if txo was sent from external account to this account",
        'is_spent': "true if txo is spent",
        'is_mine': "payment to one of your accounts, only available when it can be determined",
        'type': "one of 'claim', 'support' or 'purchase'",
        'name': "when type is 'claim' or 'support', this is the claim name",
        'claim_id': "when type is 'claim', 'support' or 'purchase', this is the claim id",
        'claim_op': "when type is 'claim', this determines if it is 'create' or 'update'",
        'value': "when type is 'claim' or 'support' with payload, this is the decoded protobuf payload",
        'value_type': "determines the type of the 'value' field: 'channel', 'stream', etc",
        'protobuf': "hex encoded raw protobuf version of 'value' field",
        'permanent_url': "when type is 'claim' or 'support', this is the long permanent claim URL",
        'claim': "for purchase outputs only, metadata of purchased claim",
        'reposted_claim': "for repost claims only, metadata of claim being reposted",
        'signing_channel': "for signed claims only, metadata of signing channel",
        'is_channel_signature_valid': "for signed claims only, whether signature is valid",
        'purchase_receipt': "metadata for the purchase transaction associated with this claim"
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


def encode_wallet_doc():
    return {
        'id': 'wallet_id',
        'name': 'optional wallet name',
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
        'claim_name': '(str) None if claim is not found else the claim name',
        'reflector_progress': '(int) reflector upload progress, 0 to 100',
        'uploading_to_reflector': '(bool) set to True when currently uploading to reflector'
    }


class JSONResponseEncoder(JSONEncoder):

    def __init__(self, *args, ledger: Ledger, include_protobuf=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledger = ledger
        self.include_protobuf = include_protobuf

    def default(self, obj):  # pylint: disable=method-hidden,arguments-differ,too-many-return-statements
        if isinstance(obj, Account):
            return self.encode_account(obj)
        if isinstance(obj, Wallet):
            return self.encode_wallet(obj)
        if isinstance(obj, ManagedStream):
            return self.encode_file(obj)
        if isinstance(obj, TorrentSource):
            return self.encode_file(obj)
        if isinstance(obj, Transaction):
            return self.encode_transaction(obj)
        if isinstance(obj, Output):
            return self.encode_output(obj)
        if isinstance(obj, Claim):
            return self.encode_claim(obj)
        if isinstance(obj, PubKey):
            return obj.extended_key_string()
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
        if not txo:
            return
        tx_height = txo.tx_ref.height
        best_height = self.ledger.headers.height
        output = {
            'txid': txo.tx_ref.id,
            'nout': txo.position,
            'height': tx_height,
            'amount': dewies_to_lbc(txo.amount),
            'address': txo.get_address(self.ledger) if txo.has_address else None,
            'confirmations': (best_height+1) - tx_height if tx_height > 0 else tx_height,
            'timestamp': self.ledger.headers.estimated_timestamp(tx_height)
        }
        if txo.is_spent is not None:
            output['is_spent'] = txo.is_spent
        if txo.is_my_output is not None:
            output['is_my_output'] = txo.is_my_output
        if txo.is_my_input is not None:
            output['is_my_input'] = txo.is_my_input
        if txo.sent_supports is not None:
            output['sent_supports'] = dewies_to_lbc(txo.sent_supports)
        if txo.sent_tips is not None:
            output['sent_tips'] = dewies_to_lbc(txo.sent_tips)
        if txo.received_tips is not None:
            output['received_tips'] = dewies_to_lbc(txo.received_tips)
        if txo.is_internal_transfer is not None:
            output['is_internal_transfer'] = txo.is_internal_transfer

        if txo.script.is_claim_name:
            output['type'] = 'claim'
            output['claim_op'] = 'create'
        elif txo.script.is_update_claim:
            output['type'] = 'claim'
            output['claim_op'] = 'update'
        elif txo.script.is_support_claim:
            output['type'] = 'support'
        elif txo.script.is_return_data:
            output['type'] = 'data'
        elif txo.purchase is not None:
            output['type'] = 'purchase'
            output['claim_id'] = txo.purchased_claim_id
            if txo.purchased_claim is not None:
                output['claim'] = self.encode_output(txo.purchased_claim)
        else:
            output['type'] = 'payment'

        if txo.script.is_claim_involved:
            output.update({
                'name': txo.claim_name,
                'normalized_name': txo.normalized_name,
                'claim_id': txo.claim_id,
                'permanent_url': txo.permanent_url,
                'meta': self.encode_claim_meta(txo.meta.copy())
            })
            if 'short_url' in output['meta']:
                output['short_url'] = output['meta'].pop('short_url')
            if 'canonical_url' in output['meta']:
                output['canonical_url'] = output['meta'].pop('canonical_url')
            if txo.claims is not None:
                output['claims'] = [self.encode_output(o) for o in txo.claims]
            if txo.reposted_claim is not None:
                output['reposted_claim'] = self.encode_output(txo.reposted_claim)
            if txo.script.is_claim_name or txo.script.is_update_claim:
                try:
                    output['value'] = txo.claim
                    output['value_type'] = txo.claim.claim_type
                    if self.include_protobuf:
                        output['protobuf'] = hexlify(txo.claim.to_bytes())
                    if txo.purchase_receipt is not None:
                        output['purchase_receipt'] = self.encode_output(txo.purchase_receipt)
                    if txo.claim.is_channel:
                        output['has_signing_key'] = txo.has_private_key
                    if check_signature and txo.claim.is_signed:
                        if txo.channel is not None:
                            output['signing_channel'] = self.encode_output(txo.channel)
                            output['is_channel_signature_valid'] = txo.is_signed_by(txo.channel, self.ledger)
                        else:
                            output['signing_channel'] = {'channel_id': txo.claim.signing_channel_id}
                            output['is_channel_signature_valid'] = False
                except DecodeError:
                    pass
        return output

    def encode_claim_meta(self, meta):
        for key, value in meta.items():
            if key.endswith('_amount'):
                if isinstance(value, int):
                    meta[key] = dewies_to_lbc(value)
        if 0 < meta.get('creation_height', 0) <= self.ledger.headers.height:
            meta['creation_timestamp'] = self.ledger.headers.estimated_timestamp(meta['creation_height'])
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

    @staticmethod
    def encode_wallet(wallet):
        return {
            'id': wallet.id,
            'name': wallet.name
        }

    def encode_file(self, managed_stream):
        output_exists = managed_stream.output_file_exists
        tx_height = managed_stream.stream_claim_info.height
        best_height = self.ledger.headers.height
        is_stream = hasattr(managed_stream, 'stream_hash')
        return {
            'streaming_url': managed_stream.stream_url if is_stream else None,
            'completed': managed_stream.completed,
            'file_name': managed_stream.file_name if output_exists else None,
            'download_directory': managed_stream.download_directory if output_exists else None,
            'download_path': managed_stream.full_path if output_exists else None,
            'points_paid': 0.0,
            'stopped': not managed_stream.running,
            'stream_hash': managed_stream.stream_hash if is_stream else None,
            'stream_name': managed_stream.descriptor.stream_name if is_stream else None,
            'suggested_file_name': managed_stream.descriptor.suggested_file_name if is_stream else None,
            'sd_hash': managed_stream.descriptor.sd_hash if is_stream else None,
            'mime_type': managed_stream.mime_type if is_stream else None,
            'key': managed_stream.descriptor.key if is_stream else None,
            'total_bytes_lower_bound': managed_stream.descriptor.lower_bound_decrypted_length() if is_stream else None,
            'total_bytes': managed_stream.descriptor.upper_bound_decrypted_length() if is_stream else None,
            'written_bytes': managed_stream.written_bytes if is_stream else None,
            'blobs_completed': managed_stream.blobs_completed if is_stream else None,
            'blobs_in_stream': managed_stream.blobs_in_stream if is_stream else None,
            'blobs_remaining': managed_stream.blobs_remaining if is_stream else None,
            'status': managed_stream.status,
            'claim_id': managed_stream.claim_id,
            'txid': managed_stream.txid,
            'nout': managed_stream.nout,
            'outpoint': managed_stream.outpoint,
            'metadata': managed_stream.metadata,
            'protobuf': managed_stream.metadata_protobuf,
            'channel_claim_id': managed_stream.channel_claim_id,
            'channel_name': managed_stream.channel_name,
            'claim_name': managed_stream.claim_name,
            'content_fee': managed_stream.content_fee,
            'purchase_receipt': self.encode_output(managed_stream.purchase_receipt),
            'added_on': managed_stream.added_on,
            'height': tx_height,
            'confirmations': (best_height + 1) - tx_height if tx_height > 0 else tx_height,
            'timestamp': self.ledger.headers.estimated_timestamp(tx_height),
            'is_fully_reflected': managed_stream.is_fully_reflected if is_stream else False,
            'reflector_progress': managed_stream.reflector_progress if is_stream else False,
            'uploading_to_reflector': managed_stream.uploading_to_reflector if is_stream else False
        }

    def encode_claim(self, claim):
        encoded = getattr(claim, claim.claim_type).to_dict()
        if 'public_key' in encoded:
            encoded['public_key_id'] = self.ledger.public_key_to_address(
                unhexlify(encoded['public_key'])
            )
        return encoded
