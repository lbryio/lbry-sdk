import asyncio

from typing import Any, Optional, Text, Tuple, Union, Sequence, Generic


class ClientFactoryMixin(asyncio.Protocol, asyncio.DatagramProtocol):
    def __init__(self):
        self.received_server_version = asyncio.Future()
        self.sent_stream_info = asyncio.Future()
    
    def connection_made(self, transport: asyncio.SubprocessTransport):
        ...
    
    def data_received(self, data: bytes):
        ...
    
    def eof_received(self):
        ...
    
    def connection_lost(self, exc: Optional[Exception]):
        ...


class BlobFactoryMixin(asyncio.Protocol, asyncio.SubprocessProtocol):
    def __init__(self, *args, **kwargs):
        asyncio.set_child_watcher(self.pipe_data_received)
        super().__init__(args, kwargs)
    
    def pipe_data_received(self, fd: int, data: Union[bytes, Text]):
        ...
    
    def pipe_connection_lost(self, fd: int, exc: Optional[Exception]):
        ...
    
    def process_exited(self):
        ...


class ReflectorClient(asyncio.Protocol):
    def __init__(self, lbry_file: Any[Generic]):
        self.lbry_file = lbry_file
        self.stream_descriptor = asyncio.Future()
        self.stream_hash = asyncio.Future()
        self.sd_hash = asyncio.Future()
        
    def connection_made(self, transport: asyncio.Transport):
        ...
    
    def datagram_received(self, data: Union[bytes, Text], addr: Tuple[str, int]):
        ...
    
    def error_received(self, exc: Exception):
        ...
    
    def connection_lost(self, exc: Optional[Exception]):
        ...


class EncryptedFileProtocol(asyncio.SubprocessProtocol):
    def __init__(self):
        self.failed_blob_hashes = asyncio.Queue()
        self.blobs_reflected = asyncio.Queue()

    def pipe_data_received(self, fd: int, data: Union[bytes, Text]):
        ...
    
    def pipe_connection_lost(self, fd: int, exc: Optional[Exception]):
        ...


class EncryptedFileClient(asyncio.StreamReaderProtocol):
    def __init__(self, blob_manager: Any, blobs: Any[Sequence]):
        read_handle, _ = ReflectorClient(lbry_file=blobs)
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
