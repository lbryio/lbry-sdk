import asyncio
import binascii
import json
import random
import typing
import logging
import functools
import selectors
from lbrynet import conf

if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.blob.blob_file import BlobFile
    from lbrynet.stream.descriptor import StreamDescriptor

# Global variables ok to export
REFLECTOR_V1 = 0
REFLECTOR_V2 = 1
PROD_SERVER = random.choice(conf.settings['reflector_servers'])

log = logging.getLogger(__name__)


class ReflectorClientVersionError(Exception):
    """
    Raised by reflector server if client sends an incompatible or unknown version.
    """


class ReflectorRequestError(Exception):
    """
    Raised by reflector server if client sends a message without the required fields.
    """


class ReflectorRequestDecodeError(Exception):
    """
    Raised by reflector server if client sends an invalid json request.
    """


class IncompleteResponse(Exception):
    """
    Raised by reflector server when client sends a portion of a json request,
    used buffering the incoming request.
    """


# SD_BLOB_SIZE = 'sd_blob_size'
# SEND_SD_BLOB = 'send_sd_blob'
# NEEDED_SD_BLOBS = 'needed_sd_blobs'
# RECEIVED_SD_BLOB = 'received_sd_blob'
# BLOB_HASH = 'blob_hash'
# BLOB_SIZE = 'blob_size'
# SEND_BLOB = 'send_blob'
# RECEIVED_BLOB = 'received_blob'
# TODO: full conversation vocabulary

# Comprehension of expected server response
# split '_' in response to get list of context vars for task
# __ vars should not be used inside ReflectorProtocol
# TODO: possibly resurrect common.py to store comprehensions
# blob or sd

# sd or hash or size or blob
_SD = bool
# if _SD add 'sd_' to all key/vals and flag
__HASH = 'hash'
__SIZE = 'size'
__BLOB = 'blob'
# if sd, strip and flag.
# just set sd to None by default.
_INFO = bool
_BLOB = 'blob'  # ACK-SYN
BLOB_KEY = ""
BLOB = {}
PAYLOAD = None
if _INFO:
    PAYLOAD = BLOB[__HASH], BLOB[__SIZE]
if _SD:
    pass
__SEND = 'send'
__RECV = 'received'
__NEED = 'needed'
_VER = 'version'
# not including version to inform subscriber
# that server version was received during handling.
_PREFIX = __SEND or __NEED or __RECV

if _SD:
    _BASE = __BLOB or _SD and __BLOB
# __SEND is SYN
# __NEED is SYN-ACK
# __RECV is ACK
_REQUEST = {_BLOB: _INFO}
_RESPONSE = {_PREFIX: _BASE}
_HANDSHAKE = {_VER: REFLECTOR_V2}
# TODO: abstract method to call ReflectorClient.send(sd_blob/blob)
# TODO: abstract method to call ReflectorClient.recv(sd/blob)
# TODO: abstract method to call ReflectorClient.MissingBlobs()


async def _request(req=dict) -> str:
    # TODO: during testing this is only way i got to work, doesn't feel right.
    return await binascii.hexlify(json.dumps(req).encode()).decode()


async def _response(resp) -> dict:
    return await json.loads(binascii.unhexlify(resp))


class ReflectorProtocol(asyncio.Protocol):
    def __init__(self, **kwargs):
        # by default look for version in kwarg otherwise just send v2.
        if not kwargs.get('version'):
            self.command = _HANDSHAKE
        # TODO: callback version
        '''
        if args is _REQUEST:
            ...  # TODO: client
        elif args is _RESPONSE:
            ...  # TODO: server
        else:
            ...  # TODO: context handler
        '''

    async def connection_made(self, transport: asyncio.Transport):
        await transport.write(self.command)
    
    async def data_received(self, data: bytes):
        msg = await _response(data.decode())
        if 'needed' in msg.keys():
            # TODO: missing blobs
            ...
        # TODO: send, received, needed
        #     'send_sd_blob': bool
        #     'needed_blobs': list, conditional
        
    async def connection_lost(self, exc: typing.Optional[Exception]):
        return exc if exc else log.info('reflected future')


class ReflectorClient(asyncio.Protocol):
    """Reflector Facade"""
    __loop = asyncio.get_event_loop()
    
    def __init__(self):
        self.needed_blobs = []
        asyncio.get_event_loop().call_soon_threadsafe(ReflectorClient.Handshake)

    def data_received(self, data: bytes):
        msg = json.loads(binascii.unhexlify(data))
        response = [element for element in msg if _RESPONSE in element]
        if not response:
            # TODO: handle command
            ...
        
    @staticmethod
    async def reflect_stream(loop: asyncio.SelectorEventLoop) -> typing.List[str]:
        fut = loop.call_soon_threadsafe(ReflectorClient.BlobHashes)
        return typing.cast(typing.List, fut)
    
    async def connection_lost(self, exc: typing.Optional[Exception]):
        self.__loop.call_soon_threadsafe(self.__loop.shutdown_asyncgens)
        asyncio.run(log.info(exc if exc else 'Closing connection.'))
        await self.__loop.close()

    

    class MissingBlobs(asyncio.Handle):
        """Handler to mitigate blobs_needed response."""
        __loop = asyncio.get_running_loop()
        
        def __init__(self, needed: typing.List, manager: BlobFileManager):
            super(ReflectorClient.MissingBlobs,self).__init__(
                args=[needed, manager],
                loop=self.__loop,
                callback=ReflectorClient.BlobHashes)
            self.needed = needed
            self.manager = manager
            await self._run()
            
        def _run(self):
            # TODO: actual mapping pattern
            """
            blobs = await
            blobs_to_send = []
            for _, element in enumerate(self.needed):
                for _k, _e in enumerate(self.manager.get_all_verified_blobs()):
                    if _e == element:
                        writer = BlobFile.open_for_writing(element)
                        writer.write(_e)
            """

        def cancel(self):
            return self.__loop.call_soon_threadsafe(self.__loop.shutdown_asyncgens)
    
    class BlobHashes(asyncio.Handle):
        """Handler to handle blob transactions."""
        __loop = asyncio.get_running_loop()
        
        def __init__(self, blob_hash: typing.AnyStr, blob_size: typing.Sized):
            self.blob_hash = blob_hash
            self.blob_size = blob_size
            super(ReflectorClient.BlobHashes, self).__init__(
                args=[blob_hash, blob_size],
                callback=ReflectorClient.Reflect,
                loop=self.__loop)
            await self._run()
        
        def cancel(self):
            self.__loop.call_soon_threadsafe(self.__loop.shutdown_asyncgens)
    
    class Reflect(asyncio.Handle):
        """Handler for sending verified blobs to server"""
        __loop = asyncio.get_running_loop()
        
        def __init__(self, blobs: typing.List):
            super(ReflectorClient.Reflect, self).__init__(
                args=[blobs],
                callback=ReflectorClient.connection_lost,
                loop=self.__loop)
            self.blob_hashes = [blobs]
            await self._run()
        
        def _run(self):
            #  TODO: get blob_hashes
            #  self.blob_hashes.get_blob(blob_hash=).open_for_writing()
            ...

    class Streaming(asyncio.Handle):
        """Handler for reflecting streaming blobs"""
        __loop = asyncio.get_running_loop()
        
        def __init__(self, blob_manager: BlobFileManager):
            super(ReflectorClient.Streaming, self).__init__(
                args=[blob_manager],
                callback=ReflectorClient.Streaming,
                loop=self.__loop)
            self.blob_manager = blob_manager
            await self._run()
            
        def _run(self):
            ...

'''
############# Stream descriptor requests and responses #############
(if sending blobs directly this is skipped)
If the client is reflecting a whole stream, they send a stream descriptor request:
{
    'sd_blob_hash': str,
    'sd_blob_size': int
}

The server indicates if it's aware of this stream already by requesting (or not requesting)
the stream descriptor blob. If the server has a validated copy of the sd blob, it will
include the needed_blobs field (a list of blob hashes missing from reflector) in the response.
If the server does not have the sd blob the needed_blobs field will not be included, as the
server does not know what blobs it is missing - so the client should send all of the blobs
in the stream.
{
    'send_sd_blob': bool
    'needed_blobs': list, conditional
}

The client may begin the file transfer of the sd blob if send_sd_blob was True.
If the client sends the blob, after receiving it the server indicates if the
transfer was successful:
{
    'received_sd_blob': bool
}
If the transfer was not successful (False), the blob is added to the needed_blobs queue
    ############# Blob requests and responses #############
    A client with blobs to reflect (either populated by the client or by the stream descriptor
    response) queries if the server is ready to begin transferring a blob
    {
        'blob_hash': str,
        'blob_size': int
    }

    The server replies, send_blob will be False if the server has a validated copy of the blob:
    {
        'send_blob': bool
    }

    The client may begin the raw blob file transfer if the server replied True.
    If the client sends the blob, the server replies:
    {
        'received_blob': bool
    }
    If the transfer was not successful (False), the blob is re-added to the needed_blobs queue

    Blob requests continue for each of the blobs the client has queued to send, when completed
    the client disconnects.
'''

# @defer.inlineCallbacks
# def _reflect_stream(blob_manager, stream_hash, sd_hash, reflector_server):
#     reflector_address, reflector_port = reflector_server[0], reflector_server[1]
#     factory = EncryptedFileReflectorClientFactory(blob_manager, stream_hash, sd_hash)
#     ip = yield resolve(reflector_address)
#     yield reactor.connectTCP(ip, reflector_port, factory)
#     result = yield factory.finished_deferred
#     defer.returnValue(result)
#
#
# def _reflect_file(lbry_file, reflector_server):
#     return _reflect_stream(lbry_file.blob_manager, lbry_file.stream_hash, lbry_file.sd_hash, reflector_server)
#
#
# def reflect_file(lbry_file, reflector_server=None):
#     if reflector_server:
#         if len(reflector_server.split(":")) == 2:
#             host, port = tuple(reflector_server.split(":"))
#             reflector_server = host, int(port)
#         else:
#             reflector_server = reflector_server, 5566
#     else:
#         reflector_server = random.choice(conf.settings['reflector_servers'])
#     return _reflect_file(lbry_file, reflector_server)
#
#
# @defer.inlineCallbacks
# def reflect_stream(blob_manager, stream_hash, reflector_server=None):
#     if reflector_server:
#         if len(reflector_server.split(":")) == 2:
#             host, port = tuple(reflector_server.split(":"))
#             reflector_server = host, int(port)
#         else:
#             reflector_server = reflector_server, 5566
#     else:
#         reflector_server = random.choice(conf.settings['reflector_servers'])
#     sd_hash = yield blob_manager.storage.get_sd_blob_hash_for_stream(stream_hash)
#     result = yield _reflect_stream(blob_manager, stream_hash, sd_hash, reflector_server)
#     defer.returnValue(result)


# import json
# import logging
# import random
# from twisted.internet.error import ConnectionRefusedError
# from twisted.protocols.basic import FileSender
# from twisted.internet.protocol import Protocol, ClientFactory
# from twisted.internet import defer, error, reactor
# from lbrynet import conf
#
# log = logging.getLogger(__name__)
#
#
# REFLECTOR_V1 = 0
# REFLECTOR_V2 = 1
#
#
# class ReflectorClientVersionError(Exception):
#     """
#     Raised by reflector server if client sends an incompatible or unknown version
#     """
#
#
# class ReflectorRequestError(Exception):
#     """
#     Raised by reflector server if client sends a message without the required fields
#     """
#
#
# class ReflectorRequestDecodeError(Exception):
#     """
#     Raised by reflector server if client sends an invalid json request
#     """
#
#
# class IncompleteResponse(Exception):
#     """
#     Raised by reflector server when client sends a portion of a json request,
#     used buffering the incoming request
#     """
#
#
# class EncryptedFileReflectorClient(Protocol):
#     #  Protocol stuff
#     def connectionMade(self):
#         log.debug("Connected to reflector")
#         self.response_buff = b''
#         self.outgoing_buff = b''
#         self.blob_hashes_to_send = []
#         self.failed_blob_hashes = []
#         self.next_blob_to_send = None
#         self.read_handle = None
#         self.sent_stream_info = False
#         self.received_descriptor_response = False
#         self.received_server_version = False
#         self.server_version = None
#         self.stream_descriptor = None
#         self.descriptor_needed = None
#         self.needed_blobs = []
#         self.reflected_blobs = []
#         self.file_sender = None
#         self.producer = None
#         self.streaming = False
#
#         self.blob_manager = self.factory.blob_manager
#         self.protocol_version = self.factory.protocol_version
#         self.stream_hash = self.factory.stream_hash
#         self.sd_hash = self.factory.sd_hash
#
#         d = self.load_descriptor()
#         d.addCallback(lambda _: self.send_handshake())
#         d.addErrback(lambda err: log.warning("An error occurred immediately: %s", err.getTraceback()))
#
#     def dataReceived(self, data):
#         self.response_buff += data
#         try:
#             msg = self.parse_response(self.response_buff)
#         except IncompleteResponse:
#             pass
#         else:
#             self.response_buff = b''
#             d = self.handle_response(msg)
#             d.addCallback(lambda _: self.send_next_request())
#             d.addErrback(self.response_failure_handler)
#
#     def store_result(self, result):
#         if not self.needed_blobs or len(self.reflected_blobs) == len(self.needed_blobs):
#             reflected = True
#         else:
#             reflected = False
#
#         d = f2d(self.blob_manager.storage.update_reflected_stream(
#             self.sd_hash, self.transport.getPeer().host, reflected
#         ))
#         d.addCallback(lambda _: result)
#         return d
#
#     def connectionLost(self, reason):
#         # make sure blob file readers get closed
#         self.set_not_uploading()
#
#         if reason.check(error.ConnectionDone):
#             if not self.needed_blobs:
#                 log.info("Reflector has all blobs for %s", self.stream_descriptor)
#             elif not self.reflected_blobs:
#                 log.info("No more completed blobs for %s to reflect, %i are still needed",
#                          self.stream_descriptor, len(self.needed_blobs))
#             else:
#                 log.info('Finished sending reflector %i blobs for %s',
#                          len(self.reflected_blobs), self.stream_descriptor)
#             result = self.reflected_blobs
#         elif reason.check(error.ConnectionLost):
#             log.warning("Stopped reflecting %s after sending %i blobs",
#                         self.stream_descriptor, len(self.reflected_blobs))
#             result = self.reflected_blobs
#         else:
#             log.info('Reflector finished for %s: %s', self.stream_descriptor,
#                      reason)
#             result = reason
#         self.factory.finished_deferred.addCallback(self.store_result)
#         self.factory.finished_deferred.callback(result)
#
#     #  IConsumer stuff
#
#     def registerProducer(self, producer, streaming):
#         self.producer = producer
#         self.streaming = streaming
#         if self.streaming is False:
#             from twisted.internet import reactor
#             reactor.callLater(0, self.producer.resumeProducing)
#
#     def unregisterProducer(self):
#         self.producer = None
#
#     def write(self, data):
#         self.transport.write(data)
#         if self.producer is not None and self.streaming is False:
#             from twisted.internet import reactor
#             reactor.callLater(0, self.producer.resumeProducing)
#
#     def get_validated_blobs(self, blobs_in_stream):
#         def get_blobs(blobs):
#             for crypt_blob in blobs:
#                 if crypt_blob.blob_hash and crypt_blob.length:
#                     yield self.blob_manager.get_blob(crypt_blob.blob_hash, crypt_blob.length)
#         return [blob for blob in get_blobs(blobs_in_stream) if blob.get_is_verified()]
#
#     def set_blobs_to_send(self, blobs_to_send):
#         for blob in blobs_to_send:
#             if blob.blob_hash not in self.blob_hashes_to_send:
#                 self.blob_hashes_to_send.append(blob.blob_hash)
#
#     def get_blobs_to_send(self):
#         def _show_missing_blobs(filtered):
#             if filtered:
#                 needs_desc = "" if not self.descriptor_needed else "descriptor and "
#                 log.info("Reflector needs %s%i blobs for stream",
#                          needs_desc,
#                          len(filtered))
#             return filtered
#
#         d = f2d(self.factory.blob_manager.storage.get_blobs_for_stream(self.stream_hash))
#         d.addCallback(self.get_validated_blobs)
#         if not self.descriptor_needed:
#             d.addCallback(lambda filtered:
#                           [blob for blob in filtered if blob.blob_hash in self.needed_blobs])
#         d.addCallback(_show_missing_blobs)
#         d.addCallback(self.set_blobs_to_send)
#         d.addCallback(lambda _: None if self.descriptor_needed else self.set_not_uploading())
#         return d
#
#     def send_request(self, request_dict):
#         self.write(json.dumps(request_dict).encode())
#
#     def send_handshake(self):
#         self.send_request({'version': self.protocol_version})
#
#     @defer.inlineCallbacks
#     def load_descriptor(self):
#         if self.sd_hash:
#             self.stream_descriptor = yield self.factory.blob_manager.get_blob(self.sd_hash)
#         else:
#             raise ValueError("no sd hash for stream %s" % self.stream_hash)
#
#     def parse_response(self, buff):
#         try:
#             return json.loads(buff)
#         except ValueError:
#             raise IncompleteResponse()
#
#     def response_failure_handler(self, err):
#         log.warning("An error occurred handling the response: %s", err.getTraceback())
#
#     def handle_response(self, response_dict):
#         if not self.received_server_version:
#             return self.handle_handshake_response(response_dict)
#         elif not self.received_descriptor_response and self.server_version == REFLECTOR_V2:
#             return self.handle_descriptor_response(response_dict)
#         else:
#             return self.handle_normal_response(response_dict)
#
#     def set_not_uploading(self):
#         if self.next_blob_to_send is not None:
#             log.debug("Close %s", self.next_blob_to_send)
#             self.read_handle.close()
#             self.read_handle = None
#             self.next_blob_to_send = None
#         if self.file_sender is not None:
#             self.file_sender.stopProducing()
#             self.file_sender = None
#         return defer.succeed(None)
#
#     def start_transfer(self):
#         assert self.read_handle is not None, \
#             "self.read_handle was None when trying to start the transfer"
#         d = self.file_sender.beginFileTransfer(self.read_handle, self)
#         d.addCallback(lambda _: self.read_handle.close())
#         return d
#
#     def handle_handshake_response(self, response_dict):
#         if 'version' not in response_dict:
#             raise ValueError("Need protocol version number!")
#         self.server_version = int(response_dict['version'])
#         if self.server_version not in [REFLECTOR_V1, REFLECTOR_V2]:
#             raise ValueError(f"I can't handle protocol version {self.server_version}!")
#         self.received_server_version = True
#         return defer.succeed(True)
#
#     def handle_descriptor_response(self, response_dict):
#         if self.file_sender is None:  # Expecting Server Info Response
#             if 'send_sd_blob' not in response_dict:
#                 raise ReflectorRequestError("I don't know whether to send the sd blob or not!")
#             if response_dict['send_sd_blob'] is True:
#                 self.file_sender = FileSender()
#             else:
#                 self.received_descriptor_response = True
#             self.descriptor_needed = response_dict['send_sd_blob']
#             self.needed_blobs = response_dict.get('needed_blobs', [])
#             return self.get_blobs_to_send()
#         else:  # Expecting Server Blob Response
#             if 'received_sd_blob' not in response_dict:
#                 raise ValueError("I don't know if the sd blob made it to the intended destination!")
#             else:
#                 self.received_descriptor_response = True
#                 disconnect = False
#                 if response_dict['received_sd_blob']:
#                     self.reflected_blobs.append(self.next_blob_to_send.blob_hash)
#                     log.info("Sent reflector descriptor %s", self.next_blob_to_send)
#                 else:
#                     log.warning("Reflector failed to receive descriptor %s",
#                                 self.next_blob_to_send)
#                     disconnect = True
#                 d = self.set_not_uploading()
#                 if disconnect:
#                     d.addCallback(lambda _: self.transport.loseConnection())
#                 return d
#
#     def handle_normal_response(self, response_dict):
#         if self.file_sender is None:  # Expecting Server Info Response
#             if 'send_blob' not in response_dict:
#                 raise ValueError("I don't know whether to send the blob or not!")
#             if response_dict['send_blob'] is True:
#                 self.file_sender = FileSender()
#                 return defer.succeed(True)
#             else:
#                 log.info("Reflector already has %s", self.next_blob_to_send)
#                 return self.set_not_uploading()
#         else:  # Expecting Server Blob Response
#             if 'received_blob' not in response_dict:
#                 raise ValueError("I don't know if the blob made it to the intended destination!")
#             else:
#                 if response_dict['received_blob']:
#                     self.reflected_blobs.append(self.next_blob_to_send.blob_hash)
#                     log.debug("Sent reflector blob %s", self.next_blob_to_send)
#                 else:
#                     log.warning("Reflector failed to receive blob %s", self.next_blob_to_send)
#                 return self.set_not_uploading()
#
#     def open_blob_for_reading(self, blob):
#         if blob.get_is_verified():
#             read_handle = blob.open_for_reading()
#             if read_handle is not None:
#                 log.debug('Getting ready to send %s', blob.blob_hash)
#                 self.next_blob_to_send = blob
#                 self.read_handle = read_handle
#                 return defer.succeed(None)
#         return defer.fail(ValueError(
#             f"Couldn't open that blob for some reason. blob_hash: {blob.blob_hash}"))
#
#     def send_blob_info(self):
#         assert self.next_blob_to_send is not None, "need to have a next blob to send at this point"
#         r = {
#             'blob_hash': self.next_blob_to_send.blob_hash,
#             'blob_size': self.next_blob_to_send.length
#         }
#         self.send_request(r)
#
#     def send_descriptor_info(self):
#         assert self.stream_descriptor is not None, "need to have a sd blob to send at this point"
#         r = {
#             'sd_blob_hash': self.stream_descriptor.blob_hash,
#             'sd_blob_size': self.stream_descriptor.length
#         }
#         self.sent_stream_info = True
#         self.send_request(r)
#
#     def skip_missing_blob(self, err, blob_hash):
#         err.trap(ValueError)
#         if blob_hash not in self.failed_blob_hashes:
#             log.warning("Failed to reflect blob %s, reason: %s",
#                         str(blob_hash)[:16], err.getTraceback())
#             self.blob_hashes_to_send.append(blob_hash)
#             self.failed_blob_hashes.append(blob_hash)
#         else:
#             log.warning("Failed second try reflecting blob %s, giving up, reason: %s",
#                         str(blob_hash)[:16], err.getTraceback())
#
#     def send_next_request(self):
#         if self.file_sender is not None:
#             # send the blob
#             return self.start_transfer()
#         elif not self.sent_stream_info:
#             # open the sd blob to send
#             blob = self.stream_descriptor
#             d = self.open_blob_for_reading(blob)
#             d.addCallbacks(lambda _: self.send_descriptor_info(),
#                            lambda err: self.skip_missing_blob(err, blob.blob_hash))
#             return d
#         elif self.blob_hashes_to_send:
#             # open the next blob to send
#             blob_hash = self.blob_hashes_to_send[0]
#             self.blob_hashes_to_send = self.blob_hashes_to_send[1:]
#             d = defer.succeed(self.blob_manager.get_blob(blob_hash))
#             d.addCallback(self.open_blob_for_reading)
#             d.addCallbacks(lambda _: self.send_blob_info(),
#                            lambda err: self.skip_missing_blob(err, blob.blob_hash))
#             return d
#         # close connection
#         self.transport.loseConnection()
#
#
# class EncryptedFileReflectorClientFactory(ClientFactory):
#     protocol = EncryptedFileReflectorClient
#     protocol_version = REFLECTOR_V2
#
#     def __init__(self, blob_manager, stream_hash, sd_hash):
#         self.blob_manager = blob_manager
#         self.stream_hash = stream_hash
#         self.sd_hash = sd_hash
#         self.p = None
#         self.finished_deferred = defer.Deferred()
#
#     def buildProtocol(self, addr):
#         p = self.protocol()
#         p.factory = self
#         self.p = p
#         return p
#
#     def startFactory(self):
#         log.debug('Starting reflector factory')
#         ClientFactory.startFactory(self)
#
#     def startedConnecting(self, connector):
#         log.debug('Connecting to reflector')
#
#     def clientConnectionLost(self, connector, reason):
#         """If we get disconnected, reconnect to server."""
#
#     def clientConnectionFailed(self, connector, reason):
#         if reason.check(ConnectionRefusedError):
#             log.warning("Could not connect to reflector server")
#         else:
#             log.error("Reflector connection failed: %s", reason)
#
#
# def _is_ip(host):
#     try:
#         if len(host.split(".")) == 4 and all([0 <= int(x) <= 255 for x in host.split(".")]):
#             return True
#         return False
#     except ValueError:
#         return False
#
#
# @defer.inlineCallbacks
# def resolve(host):
#     if _is_ip(host):
#         ip = host
#     else:
#         ip = yield reactor.resolve(host)
#     defer.returnValue(ip)
#
#

