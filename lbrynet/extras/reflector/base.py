from asyncio import AbstractEventLoop, Future,  ensure_future, wait_for
from socket import socket
from typing import Any, Optional, Callable, Tuple, Union, Sequence, Generator

REFLECTOR_V1 = 0
REFLECTOR_V2 = 1

"""
class Reflector(asyncio.AbstractEventLoopPolicy):
    def __init__(self, *args, **kwargs):
    
    
    def get_child_watcher(self):
        
        super(Reflector, self).get_child_watcher()

    def get_event_loop(self):
        
        super(Reflector, self).get_event_loop()
    
    def set_child_watcher(self, watcher: Any):
        
        super(Reflector, self).set_child_watcher(watcher)

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        
        super(Reflector, self).set_event_loop(loop)
"""


class Reflector(AbstractEventLoop):
    
    def __init__(self, protocol_version, slow_callback_duration):
        self.protocol_version = protocol_version
        self.data_transport = None
        self.stream_writer = None  # write_handle
        self.stream_reader = None  # read_handle
        self.slow_callback_duration = slow_callback_duration
    
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
    def connect_write_pipe(self, protocol_factory: ..., pipe: Any):
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
                                 local_addr: Optional[Tuple[str, int]] = ...,
                                 remote_addr: Optional[Tuple[str, int]] = ..., *,
                                 family: int = ..., proto: int = ..., flags: int = ...,
                                 reuse_address: Optional[bool] = ..., reuse_port: Optional[bool] = ...,
                                 allow_broadcast: Optional[bool] = ...,
                                 sock: Optional[socket] = ...):
        ...
    
    # TODO: BlobProtocol
    def subprocess_exec(self, protocol_factory: ..., *args: Any, stdin: Any = ...,
                        stdout: Any = ..., stderr: Any = ...,
                        **kwargs: Any):
        ...
    
    # TODO: BlobClientFactory
    def subprocess_shell(self, protocol_factory: ..., cmd: Union[bytes, str], *, stdin: Any = ...,
                         stdout: Any = ..., stderr: Any = ...,
                         **kwargs: Any):
        ...
    
    # TODO: ServerFactory
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
    
    def set_task_factory(self, factory: Optional[AbstractEventLoop]):
        ...

    def is_running(self):
        ...
    
    def is_closed(self):
        ...
    
    def create_connection(self, protocol_factory: ..., host: str = ..., port: int = ..., *,
                          ssl: ... = ..., family: int = ..., proto: int = ..., flags: int = ..., sock: Optional[socket] = ...,
                          local_addr: str = ..., server_hostname: str = ...):
        ...
