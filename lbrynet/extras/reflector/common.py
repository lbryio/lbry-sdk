import json
import logging
import socket
from asyncio import BaseProtocol


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


REFLECTOR_V1 = 0
REFLECTOR_V2 = 1
SUPPORTED_VERSION = [REFLECTOR_V1, REFLECTOR_V2]


def subscribe_client_handshake():
    cread, cwrite = socket.socketpair(family=socket.SOCK_NONBLOCK)
    # TODO: build out server

class Handshake(BaseProtocol):
    """Reflector Handshake Protocol
    
    STOMP(simple, text-oriented message protocol)
    specification for component to initiate conversation
    between performers.
    """
    protocol_version = REFLECTOR_V2
    
    def __init__(self, loop):
        self.handshake = loop.create_future()
        self.started = False
        self.data = bytearray()
        loop.run_until_complete(self.handshake)
    
    def connection_made(self, transport):
        self.started = True
        # logging.getLogger(__name__).debug('Sending handshake')
    
    def data_received(self, data):
        self.data.extend(data)
    
    def connection_lost(self, exc):
        try:
            msg = json.dumps(self.data.decode())
            # condense handshake choreography
            _ = msg['version'] if REFLECTOR_V1 | REFLECTOR_V2 else None
            # unreachable if exception
            self.handshake.set_result(self.protocol_version)
        except KeyError:
            self.handshake.set_exception(ReflectorRequestDecodeError)
        except ValueError:
            self.handshake.set_exception(ReflectorClientVersionError)
    
    def wait_closed(self):
        await self.handshake

# TODO: Logging utility to pool blocking IO away from non-blocking IO thread pool
