import asyncio
from socket import socket
from typing import Any, Optional, Text, Tuple, Union, Sequence


class ReflectorClient(asyncio.Protocol, asyncio.DatagramProtocol):
    def __init__(self):
        self.received_server_version = asyncio.ensure_future(self.connection_made)
        self.stream_descriptor = asyncio.ensure_future(self.datagram_received)
        self.stream_hash = asyncio.Future()
        self.sd_hash = asyncio.Future()
        self.sent_stream_info = asyncio.ensure_future(self.error_received)


class EncryptedFileProtocol(asyncio.StreamReaderProtocol, asyncio.SubprocessProtocol):
    def __init__(self):
        blob_read_handle, _ = ReflectorClient()
        super().__init__(stream_reader=blob_read_handle)
        self.reflected_blobs = asyncio.get_child_watcher()
        self.blob_manager = asyncio.ensure_future(self.connection_made)
        self.blobs_needed = asyncio.ensure_future(self.eof_received)
        self.blobs_reflected = asyncio.ensure_future(self.pipe_connection_lost)
        self.blob_hashes_to_send = asyncio.ensure_future(self.data_received)
        self.failed_blob_hashes = asyncio.Queue()
    
    def pipe_data_received(self, fd: int, data: Union[bytes, Text]):
        ...
    
    def pipe_connection_lost(self, fd: int, exc: Optional[Exception]):
        ...


class ReflectorClientFactory(asyncio.AbstractEventLoop):
    
    def __init__(self):
        self.protocol_version = asyncio.Future()
        self.streaming = asyncio.Lock()
        self.response_buff = bytearray()
        self.outgoing_buff = bytearray()
        self.file_sender = asyncio.ensure_future(self.create_datagram_endpoint)
        self.read_handle = asyncio.ensure_future(self.sock_recv)
        self.server_version = asyncio.ensure_future(self.sock_accept)
        # TODO: set __fspath__
        # TODO: register self.blob_manager = asyncio.ensure_future(self.subprocess_exec)
    
    # TODO: test
    slow_callback_duration = 1.0
    
    # TODO: read_handle
    # TODO: register selector
    def add_reader(self, fd: ..., callback: ..., *args: Any):
        ...
    
    # TODO: blob_handle
    # TODO: register selector
    def add_writer(self, fd: ..., callback: ..., *args: Any):
        ...
    
    # TODO: Subscriber
    # TODO: register recipient
    def add_signal_handler(self, sig: int, callback: ..., *args: Any):
        ...

    # TODO: start_handshake
    def sock_connect(self, sock: socket, address: str):
        ...

    # TODO: continue
    def sock_accept(self, sock: socket):
        ...

    # TODO: handle_handshake_response
    def sock_recv(self, sock: socket, nbytes: int):
        ...

    # TODO: send_handshake_response
    def sock_send(self, sock: socket, data: bytes):
        ...

    # TODO: reflect_encrypted_file()
    def sock_sendall(self, sock: socket, data: bytes):
        ...

    # TODO: subscribe to BlobClient
    def connect_read_pipe(self, protocol_factory: ..., pipe: Any):
        ...

    # TODO: Streaming
    def connect_write_pipe(self, protocol_factory: EncryptedFileProtocol, pipe: Any):
        ...
    
    # TODO: /is_ip()
    def getnameinfo(self, sockaddr: tuple, flags: int = ...):
        ...
    
    # TODO: /Resolver
    def getaddrinfo(self, host: Optional[str], port: Union[str, int, None], *,
                    family: int = ..., type: int = ..., proto: int = ..., flags: int = ...):
        ...
    
    # TODO: /FileSender
    def create_datagram_endpoint(self, protocol_factory: ...,
                                 local_addr: Optional[Tuple[str, int]] = ..., remote_addr: Optional[Tuple[str, int]] = ..., *,
                                 family: int = ..., proto: int = ..., flags: int = ...,
                                 reuse_address: Optional[bool] = ..., reuse_port: Optional[bool] = ...,
                                 allow_broadcast: Optional[bool] = ...,
                                 sock: Optional[socket] = ...):
        ...
    
    # TODO: BlobProtocol.connectionMade
    def subprocess_exec(self, protocol_factory: ..., *args: Any, stdin: Any = ...,
                        stdout: Any = ..., stderr: Any = ...,
                        **kwargs: Any):
        ...
    
    # TODO: BlobClientFactory
    def subprocess_shell(self, protocol_factory: ..., cmd: Union[bytes, str], *, stdin: Any = ...,
                         stdout: Any = ..., stderr: Any = ...,
                         **kwargs: Any):
        ...
    
    # TODO: ReflectorClientFactory
    def create_server(self, protocol_factory: ..., host: Union[str, Sequence[str]] = ..., port: int = ..., *,
                      family: int = ..., flags: int = ...,
                      sock: Optional[socket] = ..., backlog: int = ..., ssl: Any = ...,
                      reuse_address: Optional[bool] = ...,
                      reuse_port: Optional[bool] = ...):
        ...
    
    # TODO: shutdown
    def shutdown_asyncgens(self):
        ...
    
    # TODO: close connections
    def close(self):
        ...
    
    # TODO: everything to this LOC
    def get_task_factory(self):
        ...
