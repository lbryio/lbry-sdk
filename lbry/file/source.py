import os
import asyncio
import typing
import logging
import binascii
from typing import Optional
from lbry.utils import generate_id
from lbry.extras.daemon.storage import StoredContentClaim

if typing.TYPE_CHECKING:
    from lbry.conf import Config
    from lbry.extras.daemon.analytics import AnalyticsManager
    from lbry.wallet.transaction import Transaction
    from lbry.extras.daemon.storage import SQLiteStorage

log = logging.getLogger(__name__)


class ManagedDownloadSource:
    STATUS_RUNNING = "running"
    STATUS_STOPPED = "stopped"
    STATUS_FINISHED = "finished"

    SAVING_ID = 1
    STREAMING_ID = 2

    def __init__(self, loop: asyncio.AbstractEventLoop, config: 'Config', storage: 'SQLiteStorage', identifier: str,
                 file_name: Optional[str] = None, download_directory: Optional[str] = None,
                 status: Optional[str] = STATUS_STOPPED, claim: Optional[StoredContentClaim] = None,
                 download_id: Optional[str] = None, rowid: Optional[int] = None,
                 content_fee: Optional['Transaction'] = None,
                 analytics_manager: Optional['AnalyticsManager'] = None,
                 added_on: Optional[int] = None):
        self.loop = loop
        self.storage = storage
        self.config = config
        self.identifier = identifier
        self.download_directory = download_directory
        self._file_name = file_name
        self._status = status
        self.stream_claim_info = claim
        self.download_id = download_id or binascii.hexlify(generate_id()).decode()
        self.rowid = rowid
        self.content_fee = content_fee
        self.purchase_receipt = None
        self._added_on = added_on
        self.analytics_manager = analytics_manager

        self.saving = asyncio.Event(loop=self.loop)
        self.finished_writing = asyncio.Event(loop=self.loop)
        self.started_writing = asyncio.Event(loop=self.loop)
        self.finished_write_attempt = asyncio.Event(loop=self.loop)

    # @classmethod
    # async def create(cls, loop: asyncio.AbstractEventLoop, config: 'Config', file_path: str,
    #                  key: Optional[bytes] = None,
    #                  iv_generator: Optional[typing.Generator[bytes, None, None]] = None) -> 'ManagedDownloadSource':
    #     raise NotImplementedError()

    async def start(self, timeout: Optional[float] = None, save_now: Optional[bool] = False):
        raise NotImplementedError()

    async def stop(self, finished: bool = False):
        raise NotImplementedError()

    async def save_file(self, file_name: Optional[str] = None, download_directory: Optional[str] = None):
        raise NotImplementedError()

    def stop_tasks(self):
        raise NotImplementedError()

    # def set_claim(self, claim_info: typing.Dict, claim: 'Claim'):
    #     self.stream_claim_info = StoredContentClaim(
    #         f"{claim_info['txid']}:{claim_info['nout']}", claim_info['claim_id'],
    #         claim_info['name'], claim_info['amount'], claim_info['height'],
    #         binascii.hexlify(claim.to_bytes()).decode(), claim.signing_channel_id, claim_info['address'],
    #         claim_info['claim_sequence'], claim_info.get('channel_name')
    #     )
    #
    # async def update_content_claim(self, claim_info: Optional[typing.Dict] = None):
    #     if not claim_info:
    #         claim_info = await self.blob_manager.storage.get_content_claim(self.stream_hash)
    #     self.set_claim(claim_info, claim_info['value'])

    @property
    def file_name(self) -> Optional[str]:
        return self._file_name

    @property
    def added_on(self) -> Optional[int]:
        return self._added_on

    @property
    def status(self) -> str:
        return self._status

    @property
    def completed(self):
        raise NotImplementedError()

    # @property
    # def stream_url(self):
    #     return f"http://{self.config.streaming_host}:{self.config.streaming_port}/stream/{self.sd_hash}

    @property
    def finished(self) -> bool:
        return self.status == self.STATUS_FINISHED

    @property
    def running(self) -> bool:
        return self.status == self.STATUS_RUNNING

    @property
    def claim_id(self) -> Optional[str]:
        return None if not self.stream_claim_info else self.stream_claim_info.claim_id

    @property
    def txid(self) -> Optional[str]:
        return None if not self.stream_claim_info else self.stream_claim_info.txid

    @property
    def nout(self) -> Optional[int]:
        return None if not self.stream_claim_info else self.stream_claim_info.nout

    @property
    def outpoint(self) -> Optional[str]:
        return None if not self.stream_claim_info else self.stream_claim_info.outpoint

    @property
    def claim_height(self) -> Optional[int]:
        return None if not self.stream_claim_info else self.stream_claim_info.height

    @property
    def channel_claim_id(self) -> Optional[str]:
        return None if not self.stream_claim_info else self.stream_claim_info.channel_claim_id

    @property
    def channel_name(self) -> Optional[str]:
        return None if not self.stream_claim_info else self.stream_claim_info.channel_name

    @property
    def claim_name(self) -> Optional[str]:
        return None if not self.stream_claim_info else self.stream_claim_info.claim_name

    @property
    def metadata(self) -> Optional[typing.Dict]:
        return None if not self.stream_claim_info else self.stream_claim_info.claim.stream.to_dict()

    @property
    def metadata_protobuf(self) -> bytes:
        if self.stream_claim_info:
            return binascii.hexlify(self.stream_claim_info.claim.to_bytes())

    @property
    def full_path(self) -> Optional[str]:
        return os.path.join(self.download_directory, os.path.basename(self.file_name)) \
            if self.file_name and self.download_directory else None

    @property
    def output_file_exists(self):
        return os.path.isfile(self.full_path) if self.full_path else False
