import asyncio
import logging
import os

from lbrynet.blob.EncryptedFileCreator import create_lbry_file
from lbrynet.extras.daemon.mime_types import guess_mime_type

log = logging.getLogger(__name__)


def d2f(d):
    return d.asFuture(asyncio.get_event_loop())


class Publisher:
    def __init__(self, account, blob_manager, payment_rate_manager, storage,
                 lbry_file_manager, wallet, certificate):
        self.account = account
        self.blob_manager = blob_manager
        self.payment_rate_manager = payment_rate_manager
        self.storage = storage
        self.lbry_file_manager = lbry_file_manager
        self.wallet = wallet
        self.certificate = certificate
        self.lbry_file = None

    async def create_and_publish_stream(self, name, bid, claim_dict, file_path, holding_address=None):
        """Create lbry file and make claim"""
        log.info('Starting publish for %s', name)
        if not os.path.isfile(file_path):
            raise Exception(f"File {file_path} not found")
        if os.path.getsize(file_path) == 0:
            raise Exception(f"Cannot publish empty file {file_path}")

        file_name = os.path.basename(file_path)
        with open(file_path, 'rb') as read_handle:
            self.lbry_file = await d2f(create_lbry_file(
                self.blob_manager, self.storage, self.payment_rate_manager, self.lbry_file_manager, file_name,
                read_handle
            ))

        if 'source' not in claim_dict['stream']:
            claim_dict['stream']['source'] = {}
        claim_dict['stream']['source']['source'] = self.lbry_file.sd_hash
        claim_dict['stream']['source']['sourceType'] = 'lbry_sd_hash'
        claim_dict['stream']['source']['contentType'] = guess_mime_type(file_path)
        claim_dict['stream']['source']['version'] = "_0_0_1"  # need current version here
        tx = await self.wallet.claim_name(
            self.account, name, bid, claim_dict, self.certificate, holding_address
        )

        # check if we have a file already for this claim (if this is a publish update with a new stream)
        old_stream_hashes = await d2f(self.storage.get_old_stream_hashes_for_claim_id(
            tx.outputs[0].claim_id, self.lbry_file.stream_hash
        ))
        if old_stream_hashes:
            for lbry_file in filter(lambda l: l.stream_hash in old_stream_hashes,
                                    list(self.lbry_file_manager.lbry_files)):
                await d2f(self.lbry_file_manager.delete_lbry_file(lbry_file, delete_file=False))
                log.info("Removed old stream for claim update: %s", lbry_file.stream_hash)

        await d2f(self.storage.save_content_claim(
            self.lbry_file.stream_hash, tx.outputs[0].id
        ))
        return tx

    async def publish_stream(self, name, bid, claim_dict, stream_hash, holding_address=None):
        """Make a claim without creating a lbry file"""
        tx = await self.wallet.claim_name(
            self.account, name, bid, claim_dict, self.certificate, holding_address
        )
        if stream_hash:  # the stream_hash returned from the db will be None if this isn't a stream we have
            await d2f(self.storage.save_content_claim(
                stream_hash, tx.outputs[0].id
            ))
            self.lbry_file = [f for f in self.lbry_file_manager.lbry_files if f.stream_hash == stream_hash][0]
        return tx
