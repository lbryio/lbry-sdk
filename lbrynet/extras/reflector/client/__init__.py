import json
from asyncio import tasks, protocols, transports
from typing import Union, Text, Tuple
from functools import wraps
from lbrynet.extras.reflector import REFLECTOR_V2


def client_factory(task_factory):
    @wraps(task_factory)
    def base_protocol(loop, coro):
        next_task = tasks.Task(coro, loop=loop)
        current_task = tasks.Task.current_task(loop=loop)
        previous_task = getattr(current_task, 'current_task', None)
        setattr(next_task, 'current_task', previous_task)
    return base_protocol


class ClientProtocol(protocols.DatagramProtocol):
    def __init__(self, protocol_version=REFLECTOR_V2, addr=None):
        self._handshake_sent = False
        self._handshake_recv = False
        self.__version = protocol_version
        self.__addr = addr
    
    def connection_made(self, transport: transports.DatagramTransport):
        if not self._handshake_sent:
            payload = json.dumps({'version': self.__version})
            transport.sendto(data=payload.encode(), addr=self.__addr)
            self._handshake_sent = True

    def error_received(self, exc: Exception):
        if self._handshake_sent and not self._handshake_recv:
            self._handshake_recv = False
    
    def datagram_received(self, data: Union[bytes, Text], addr: Tuple[str, int]):
        if self._handshake_sent and not self._handshake_recv:
            msg = data.decode()
            message = json.loads(msg)
            if 'version' in message:
                if self.__version in message:
                    self._handshake_recv = True
