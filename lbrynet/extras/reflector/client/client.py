import asyncio
from typing import Any, Optional, Text, Union, Sequence


class EncryptedFileMixin(asyncio.Protocol, asyncio.StreamReaderProtocol):
    def __init__(self, blob_manager: Any, blobs: Any[Sequence]):
        read_handle, _ = blob_manager(blobs)
        super().__init__(stream_reader=read_handle)
        self.blob_manager = blob_manager
        self.blob_hashes_to_send = blobs
        self.blobs_needed = asyncio.Queue()
    
    def connection_made(self, transport):
        ...
    
    def data_received(self, data: bytes):
        ...
    
    def eof_received(self):
        ...
    
    def connection_lost(self, exc: Optional[Exception]):
        ...


class BlobMixin(asyncio.Protocol, asyncio.SubprocessProtocol):
    def __init__(self, *args, **kwargs):
        asyncio.set_child_watcher(self.pipe_data_received)
        super().__init__(args, kwargs)
    
    def pipe_data_received(self, fd: int, data: Union[bytes, Text]):
        ...
    
    def pipe_connection_lost(self, fd: int, exc: Optional[Exception]):
        ...
    
    def process_exited(self):
        ...


# TODO: reupload.py

class ReflectorClient(asyncio.AbstractServer):
    def __init__(self):
        ...

    def wait_closed(self):
        ...
    
    def close(self):
        ...
