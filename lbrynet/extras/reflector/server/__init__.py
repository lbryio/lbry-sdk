import json

from typing import Union, Text, Tuple
from asyncio import protocols, transports

from lbrynet.extras.reflector import REFLECTOR_V1, REFLECTOR_V2


class ServerProtocol(protocols.DatagramProtocol):
    def __init__(self):
        self._transport = None
        self.protocol_version = None
        self.handshake_ok = False
    
    def connection_made(self, transport: transports.Transport):
        self._transport = transport
    
    def datagram_received(self, data: Union[bytes, Text], addr: Tuple[str, int]):
        if not self.handshake_ok:
            msg = data.decode()
            message = json.dumps(msg)
            if 'version' in message:
                if REFLECTOR_V2 in message:
                    self.protocol_version = REFLECTOR_V2
                elif REFLECTOR_V1 in message:
                    self.protocol_version = REFLECTOR_V1
            if self.protocol_version:
                self._transport.write(json.loads({'version': self.protocol_version}))
                self.handshake_ok = True
            else:
                self._transport.close()
