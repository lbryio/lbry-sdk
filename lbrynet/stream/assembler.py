import os
import binascii
import logging
import typing
import asyncio
from lbrynet.blob import MAX_BLOB_SIZE
from lbrynet.stream.descriptor import StreamDescriptor
if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.blob.blob_info import BlobInfo
    from lbrynet.blob.blob_file import BlobFile


log = logging.getLogger(__name__)


def _get_next_available_file_name(download_directory: str, file_name: str) -> str:
    base_name, ext = os.path.splitext(os.path.basename(file_name))
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
        self.got_descriptor = asyncio.Event(loop=self.loop)
        self.wrote_bytes_event = asyncio.Event(loop=self.loop)
        self.stream_finished_event = asyncio.Event(loop=self.loop)
        self.output_path = ''
        self.stream_handle = None
        self.written_bytes: int = 0

    async def _decrypt_blob(self, blob: 'BlobFile', blob_info: 'BlobInfo', key: str):
        if not blob or self.stream_handle.closed:
            return False

        def _decrypt_and_write():
            offset = blob_info.blob_num * (MAX_BLOB_SIZE - 1)
            self.stream_handle.seek(offset)
            _decrypted = blob.decrypt(
                binascii.unhexlify(key), binascii.unhexlify(blob_info.iv.encode())
            )
            self.stream_handle.write(_decrypted)
            self.stream_handle.flush()
            self.written_bytes += len(_decrypted)
            log.debug("decrypted %s", blob.blob_hash[:8])
            self.wrote_bytes_event.set()

        await self.loop.run_in_executor(None, _decrypt_and_write)
        return True

    async def setup(self):
        pass

    async def after_got_descriptor(self):
        pass

    async def after_finished(self):
        pass

    async def assemble_decrypted_stream(self, output_dir: str, output_file_name: typing.Optional[str] = None):
        if not os.path.isdir(output_dir):
            raise OSError(f"output directory does not exist: '{output_dir}' '{output_file_name}'")
        await self.setup()
        self.sd_blob = await self.get_blob(self.sd_hash)
        self.descriptor = await StreamDescriptor.from_stream_descriptor_blob(self.loop, self.blob_manager.blob_dir,
                                                                             self.sd_blob)
        await self.after_got_descriptor()
        self.output_path = await get_next_available_file_name(self.loop, output_dir,
                                                              output_file_name or self.descriptor.suggested_file_name)
        if not self.got_descriptor.is_set():
            self.got_descriptor.set()
        await self.blob_manager.storage.store_stream(
            self.sd_blob, self.descriptor
        )
        await self.blob_manager.blob_completed(self.sd_blob)
        with open(self.output_path, 'wb') as stream_handle:
            self.stream_handle = stream_handle
            for i, blob_info in enumerate(self.descriptor.blobs[:-1]):
                if blob_info.blob_num != i:
                    log.error("sd blob %s is invalid, cannot assemble stream", self.descriptor.sd_hash)
                    return
                while not stream_handle.closed:
                    try:
                        blob = await self.get_blob(blob_info.blob_hash, blob_info.length)
                        if await self._decrypt_blob(blob, blob_info, self.descriptor.key):
                            await self.blob_manager.blob_completed(blob)
                            break
                    except FileNotFoundError:
                        log.debug("stream assembler stopped")
                        return
                    except (ValueError, IOError, OSError):
                        log.warning("failed to decrypt blob %s for stream %s", blob_info.blob_hash,
                                    self.descriptor.sd_hash)
                        continue

        self.stream_finished_event.set()
        await self.after_finished()

    async def get_blob(self, blob_hash: str, length: typing.Optional[int] = None) -> 'BlobFile':
        return self.blob_manager.get_blob(blob_hash, length)
