import json
import logging

from asyncio import tasks, protocols, transports
from typing import Optional, Union, Text, Tuple
from functools import wraps
from urllib.parse import quote_from_bytes

REFLECTOR_V1 = 0
REFLECTOR_V2 = 1


log = logging.getLogger(__name__)


class ReflectorClientVersionError(Exception):
    """
    Raised by reflector server if client sends an incompatible or unknown version
    """


class ReflectorRequestError(Exception):
    """
    Raised by reflector server if client sends a message without the required fields
    """


class ReflectorRequestDecodeError(Exception):
    """
    Raised by reflector server if client sends an invalid json request
    """


class IncompleteResponse(Exception):
    """
    Raised by reflector server when client sends a portion of a json request,
    used buffering the incoming request
    """


def reflector_factory(task_factory):
    @wraps(task_factory)
    def base_protocol(loop, coro):
        next_task = tasks.Task(coro, loop=loop)
        current_task = tasks.Task.current_task(loop=loop)
        previous_task = getattr(current_task, 'current_task', None)
        setattr(next_task, 'current_task', previous_task)
    return base_protocol


class BaseProtocol(protocols.DatagramProtocol):
    def __init__(self, protocol_version=REFLECTOR_V2, addr=None):
        self._handshake_sent = False
        self._handshake_recv = False
        self.__version = protocol_version
        self.__addr = addr
    
    def connection_made(self, transport: transports.DatagramTransport):
        if not self._handshake_sent:
            log.debug('Sending handshake')
            payload = json.dumps({'version': self.__version})
            transport.sendto(data=payload.encode(), addr=self.__addr)
            self._handshake_sent = True
        
    def connection_lost(self, exc: Optional[Exception]):
        log.info("Closing connection, reason: %s", exc)
    
    def error_received(self, exc: Exception):
        if exc is ReflectorRequestError:
            log.error("Error during handshake: %s", exc)
        elif exc is ReflectorRequestDecodeError:
            log.error("Error when decoding payload: %s", quote_from_bytes(
                json.dumps({'version': self.__version}).encode()))
        elif exc is ReflectorClientVersionError:
            log.error("Invalid reflector protocol version: %i", self.__version)
        else:
            log.error("An error occurred immediately: %s", exc)
    
    def datagram_received(self, data: Union[bytes, Text], addr: Tuple[str, int]):
        if self._handshake_sent and not self._handshake_recv:
            self._handshake_recv = True
            log.info("Data received: %s", data.decode())
            log.info("Connection established with %s", addr)
