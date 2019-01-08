import os
import binascii
import logging
import typing
import asyncio
from lbrynet.blob import MAX_BLOB_SIZE
from lbrynet.blob.blob_info import BlobInfo
from lbrynet.blob.blob_file import BlobFile
from lbrynet.stream.descriptor import StreamDescriptor
if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager


log = logging.getLogger(__name__)


def _get_next_available_file_name(download_directory: str, file_name: str) -> str:
    base_name, ext = os.path.splitext(file_name)
    i = 0
    while os.path.isfile(os.path.join(download_directory, file_name)):
        i += 1
        file_name = "%s_%i%s" % (base_name, i, ext)

    return os.path.join(download_directory, file_name)


async def get_next_available_file_name(loop: asyncio.BaseEventLoop, download_directory: str, file_name: str) -> str:
    return await loop.run_in_executor(None, _get_next_available_file_name, download_directory, file_name)


class StreamAssembler:
    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: 'BlobFileManager', sd_hash: str):
        self.loop = loop
        self.blob_manager = blob_manager
        self.sd_hash = sd_hash
        self.sd_blob: 'BlobFile' = None
        self.descriptor: StreamDescriptor = None
        self.lock = asyncio.Lock(loop=self.loop)
        self.got_descriptor = asyncio.Event(loop=self.loop)
        self.wrote_bytes_event = asyncio.Event(loop=self.loop)
        self.stream_finished_event = asyncio.Event(loop=self.loop)
        self.output_path = ''
        self.stream_handle = None
        self.written_bytes: int = 0

    async def _decrypt_blob(self, blob: 'BlobFile', blob_info: 'BlobInfo', key: str):
        offset = blob_info.blob_num * (MAX_BLOB_SIZE - 1)

        def _decrypt_and_write():
            self.stream_handle.seek(offset)
            decrypted = blob.decrypt(
                binascii.unhexlify(key), binascii.unhexlify(blob_info.iv.encode())
            )
            self.stream_handle.write(decrypted)
            self.stream_handle.flush()
            self.written_bytes += len(decrypted)
            log.info("wrote %i decrypted bytes (offset %i)", len(decrypted), offset)

        await self.lock.acquire()
        try:
            await self.loop.run_in_executor(None, _decrypt_and_write)
            if not self.wrote_bytes_event.is_set():
                self.wrote_bytes_event.set()
        finally:
            self.lock.release()
        log.debug("decrypted %s", blob.blob_hash[:8])
        return

    async def assemble_decrypted_stream(self, output_dir: str, output_file_name: typing.Optional[str] = None):
        if not os.path.isdir(output_dir):
            raise OSError(f"output directory does not exist: '{output_dir}' '{output_file_name}'")
        log.info("get descriptor")
        self.sd_blob = await self.get_blob(self.sd_hash)
        log.info("got descriptor")
        await self.blob_manager.blob_completed(self.sd_blob)
        log.info("descriptor completed")
        self.descriptor = await StreamDescriptor.from_stream_descriptor_blob(self.loop, self.blob_manager, self.sd_blob)
        if not self.got_descriptor.is_set():
            self.got_descriptor.set()
        log.info("loaded descriptor")
        self.output_path = await get_next_available_file_name(self.loop, output_dir,
                                                              output_file_name or self.descriptor.suggested_file_name)

        self.stream_handle = open(self.output_path, 'wb')
        await self.blob_manager.storage.store_stream(
            self.sd_blob, self.descriptor
        )
        log.info("added stream to db")
        try:
            for blob_info in self.descriptor.blobs[:-1]:
                log.info("get blob %s (%i)", blob_info.blob_hash, blob_info.blob_num)
                blob = await self.get_blob(blob_info.blob_hash, blob_info.length)
                # await blob.finished_writing.wait()
                log.info("got blob %s (%i), decrypt it", blob_info.blob_hash, blob_info.blob_num)
                await self._decrypt_blob(blob, blob_info, self.descriptor.key)
            self.stream_finished_event.set()
        finally:
            self.stream_handle.close()

    # override
    async def get_blob(self, blob_hash: str, length: typing.Optional[int] = None) -> 'BlobFile':
        f = asyncio.Future(loop=self.loop)
        f.set_result(self.blob_manager.get_blob(blob_hash, length))
        return await f
