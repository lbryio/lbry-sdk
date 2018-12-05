# Copyright (c) 2018, Neil Booth
#
# All rights reserved.
#
# The MIT License (MIT)
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.


__all__ = ('Connector', 'RPCSession', 'MessageSession', 'Server',
           'BatchError')


import asyncio
from asyncio import Event, CancelledError
import logging
import time
from contextlib import suppress

from .jsonrpc import Request, JSONRPCConnection, JSONRPCv2, JSONRPC, Batch, Notification
from .jsonrpc import RPCError, ProtocolError
from .curio import TaskGroup, TaskTimeout, spawn_sync, ignore_after, timeout_after
from .framing import BadMagicError, BadChecksumError, OversizedPayloadError, BitcoinFramer, NewlineFramer
from .util import Concurrency


class Connector:

    def __init__(self, session_factory, host=None, port=None, proxy=None,
                 **kwargs):
        self.session_factory = session_factory
        self.host = host
        self.port = port
        self.proxy = proxy
        self.loop = kwargs.get('loop', asyncio.get_event_loop())
        self.kwargs = kwargs

    async def create_connection(self):
        '''Initiate a connection.'''
        connector = self.proxy or self.loop
        return await connector.create_connection(
            self.session_factory, self.host, self.port, **self.kwargs)

    async def __aenter__(self):
        transport, self.protocol = await self.create_connection()
        # By default, do not limit outgoing connections
        self.protocol.bw_limit = 0
        return self.protocol

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.protocol.close()


class SessionBase(asyncio.Protocol):
    '''Base class of networking sessions.

    There is no client / server distinction other than who initiated
    the connection.

    To initiate a connection to a remote server pass host, port and
    proxy to the constructor, and then call create_connection().  Each
    successful call should have a corresponding call to close().

    Alternatively if used in a with statement, the connection is made
    on entry to the block, and closed on exit from the block.
    '''

    max_errors = 10

    def __init__(self, *, framer=None, loop=None):
        self.framer = framer or self.default_framer()
        self.loop = loop or asyncio.get_event_loop()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.transport = None
        # Set when a connection is made
        self._address = None
        self._proxy_address = None
        # For logger.debug messsages
        self.verbosity = 0
        # Cleared when the send socket is full
        self._can_send = Event()
        self._can_send.set()
        self._pm_task = None
        self._task_group = TaskGroup()
        # Force-close a connection if a send doesn't succeed in this time
        self.max_send_delay = 60
        # Statistics.  The RPC object also keeps its own statistics.
        self.start_time = time.time()
        self.errors = 0
        self.send_count = 0
        self.send_size = 0
        self.last_send = self.start_time
        self.recv_count = 0
        self.recv_size = 0
        self.last_recv = self.start_time
        # Bandwidth usage per hour before throttling starts
        self.bw_limit = 2000000
        self.bw_time = self.start_time
        self.bw_charge = 0
        # Concurrency control
        self.max_concurrent = 6
        self._concurrency = Concurrency(self.max_concurrent)

    async def _update_concurrency(self):
        # A non-positive value means not to limit concurrency
        if self.bw_limit <= 0:
            return
        now = time.time()
        # Reduce the recorded usage in proportion to the elapsed time
        refund = (now - self.bw_time) * (self.bw_limit / 3600)
        self.bw_charge = max(0, self.bw_charge - int(refund))
        self.bw_time = now
        # Reduce concurrency allocation by 1 for each whole bw_limit used
        throttle = int(self.bw_charge / self.bw_limit)
        target = max(1, self.max_concurrent - throttle)
        current = self._concurrency.max_concurrent
        if target != current:
            self.logger.info(f'changing task concurrency from {current} '
                             f'to {target}')
            await self._concurrency.set_max_concurrent(target)

    def _using_bandwidth(self, size):
        '''Called when sending or receiving size bytes.'''
        self.bw_charge += size

    async def _process_messages(self):
        '''Process incoming messages asynchronously and consume the
        results.
        '''
        async def collect_tasks():
            next_done = task_group.next_done
            while True:
                await next_done()

        task_group = self._task_group
        async with task_group:
            await self.spawn(self._receive_messages)
            await self.spawn(collect_tasks)

    async def _limited_wait(self, secs):
        # Wait at most secs seconds to send, otherwise abort the connection
        try:
            async with timeout_after(secs):
                await self._can_send.wait()
        except TaskTimeout:
            self.abort()
            raise

    async def _send_message(self, message):
        if not self._can_send.is_set():
            await self._limited_wait(self.max_send_delay)
        if not self.is_closing():
            framed_message = self.framer.frame(message)
            self.send_size += len(framed_message)
            self._using_bandwidth(len(framed_message))
            self.send_count += 1
            self.last_send = time.time()
            if self.verbosity >= 4:
                self.logger.debug(f'Sending framed message {framed_message}')
            self.transport.write(framed_message)

    def _bump_errors(self):
        self.errors += 1
        if self.errors >= self.max_errors:
            # Don't await self.close() because that is self-cancelling
            self._close()

    def _close(self):
        if self.transport:
            self.transport.close()

    # asyncio framework
    def data_received(self, framed_message):
        '''Called by asyncio when a message comes in.'''
        if self.verbosity >= 4:
            self.logger.debug(f'Received framed message {framed_message}')
        self.recv_size += len(framed_message)
        self._using_bandwidth(len(framed_message))
        self.framer.received_bytes(framed_message)

    def pause_writing(self):
        '''Transport calls when the send buffer is full.'''
        if not self.is_closing():
            self._can_send.clear()
            self.transport.pause_reading()

    def resume_writing(self):
        '''Transport calls when the send buffer has room.'''
        if not self._can_send.is_set():
            self._can_send.set()
            self.transport.resume_reading()

    def connection_made(self, transport):
        '''Called by asyncio when a connection is established.

        Derived classes overriding this method must call this first.'''
        self.transport = transport
        # This would throw if called on a closed SSL transport.  Fixed
        # in asyncio in Python 3.6.1 and 3.5.4
        peer_address = transport.get_extra_info('peername')
        # If the Socks proxy was used then _address is already set to
        # the remote address
        if self._address:
            self._proxy_address = peer_address
        else:
            self._address = peer_address
        self._pm_task = spawn_sync(self._process_messages(), loop=self.loop)

    def connection_lost(self, exc):
        '''Called by asyncio when the connection closes.

        Tear down things done in connection_made.'''
        self._address = None
        self.transport = None
        self._pm_task.cancel()
        # Release waiting tasks
        self._can_send.set()

    # External API
    def default_framer(self):
        '''Return a default framer.'''
        raise NotImplementedError

    def peer_address(self):
        '''Returns the peer's address (Python networking address), or None if
        no connection or an error.

        This is the result of socket.getpeername() when the connection
        was made.
        '''
        return self._address

    def peer_address_str(self):
        '''Returns the peer's IP address and port as a human-readable
        string.'''
        if not self._address:
            return 'unknown'
        ip_addr_str, port = self._address[:2]
        if ':' in ip_addr_str:
            return f'[{ip_addr_str}]:{port}'
        else:
            return f'{ip_addr_str}:{port}'

    async def spawn(self, coro, *args):
        '''If the session is connected, spawn a task that is cancelled
        on disconnect, and return it.  Otherwise return None.'''
        group = self._task_group
        if not group.closed():
            return await group.spawn(coro, *args)
        else:
            return None

    def is_closing(self):
        '''Return True if the connection is closing.'''
        return not self.transport or self.transport.is_closing()

    def abort(self):
        '''Forcefully close the connection.'''
        if self.transport:
            self.transport.abort()

    async def close(self, *, force_after=30):
        '''Close the connection and return when closed.'''
        self._close()
        if self._pm_task:
            with suppress(CancelledError):
                async with ignore_after(force_after):
                    await self._pm_task
                self.abort()
                await self._pm_task


class MessageSession(SessionBase):
    '''Session class for protocols where messages are not tied to responses,
    such as the Bitcoin protocol.

    To use as a client (connection-opening) session, pass host, port
    and perhaps a proxy.
    '''
    async def _receive_messages(self):
        while not self.is_closing():
            try:
                message = await self.framer.receive_message()
            except BadMagicError as e:
                magic, expected = e.args
                self.logger.error(
                    f'bad network magic: got {magic} expected {expected}, '
                    f'disconnecting'
                )
                self._close()
            except OversizedPayloadError as e:
                command, payload_len = e.args
                self.logger.error(
                    f'oversized payload of {payload_len:,d} bytes to command '
                    f'{command}, disconnecting'
                )
                self._close()
            except BadChecksumError as e:
                payload_checksum, claimed_checksum = e.args
                self.logger.warning(
                    f'checksum mismatch: actual {payload_checksum.hex()} '
                    f'vs claimed {claimed_checksum.hex()}'
                )
                self._bump_errors()
            else:
                self.last_recv = time.time()
                self.recv_count += 1
                if self.recv_count % 10 == 0:
                    await self._update_concurrency()
                await self.spawn(self._throttled_message(message))

    async def _throttled_message(self, message):
        '''Process a single request, respecting the concurrency limit.'''
        async with self._concurrency.semaphore:
            try:
                await self.handle_message(message)
            except ProtocolError as e:
                self.logger.error(f'{e}')
                self._bump_errors()
            except CancelledError:
                raise
            except Exception:
                self.logger.exception(f'exception handling {message}')
                self._bump_errors()

    # External API
    def default_framer(self):
        '''Return a bitcoin framer.'''
        return BitcoinFramer(bytes.fromhex('e3e1f3e8'), 128_000_000)

    async def handle_message(self, message):
        '''message is a (command, payload) pair.'''
        pass

    async def send_message(self, message):
        '''Send a message (command, payload) over the network.'''
        await self._send_message(message)


class BatchError(Exception):

    def __init__(self, request):
        self.request = request   # BatchRequest object


class BatchRequest(object):
    '''Used to build a batch request to send to the server.  Stores
    the

    Attributes batch and results are initially None.

    Adding an invalid request or notification immediately raises a
    ProtocolError.

    On exiting the with clause, it will:

    1) create a Batch object for the requests in the order they were
       added.  If the batch is empty this raises a ProtocolError.

    2) set the "batch" attribute to be that batch

    3) send the batch request and wait for a response

    4) raise a ProtocolError if the protocol was violated by the
       server.  Currently this only happens if it gave more than one
       response to any request

    5) otherwise there is precisely one response to each Request.  Set
       the "results" attribute to the tuple of results; the responses
       are ordered to match the Requests in the batch.  Notifications
       do not get a response.

    6) if raise_errors is True and any individual response was a JSON
       RPC error response, or violated the protocol in some way, a
       BatchError exception is raised.  Otherwise the caller can be
       certain each request returned a standard result.
    '''

    def __init__(self, session, raise_errors):
        self._session = session
        self._raise_errors = raise_errors
        self._requests = []
        self.batch = None
        self.results = None

    def add_request(self, method, args=()):
        self._requests.append(Request(method, args))

    def add_notification(self, method, args=()):
        self._requests.append(Notification(method, args))

    def __len__(self):
        return len(self._requests)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.batch = Batch(self._requests)
            message, event = self._session.connection.send_batch(self.batch)
            await self._session._send_message(message)
            await event.wait()
            self.results = event.result
            if self._raise_errors:
                if any(isinstance(item, Exception) for item in event.result):
                    raise BatchError(self)


class RPCSession(SessionBase):
    '''Base class for protocols where a message can lead to a response,
    for example JSON RPC.'''

    def __init__(self, *, framer=None, loop=None, connection=None):
        super().__init__(framer=framer, loop=loop)
        self.connection = connection or self.default_connection()

    async def _receive_messages(self):
        while not self.is_closing():
            try:
                message = await self.framer.receive_message()
            except MemoryError as e:
                self.logger.warning(f'{e!r}')
                continue

            self.last_recv = time.time()
            self.recv_count += 1
            if self.recv_count % 10 == 0:
                await self._update_concurrency()

            try:
                requests = self.connection.receive_message(message)
            except ProtocolError as e:
                self.logger.debug(f'{e}')
                if e.error_message:
                    await self._send_message(e.error_message)
                if e.code == JSONRPC.PARSE_ERROR:
                    self.max_errors = 0
                self._bump_errors()
            else:
                for request in requests:
                    await self.spawn(self._throttled_request(request))

    async def _throttled_request(self, request):
        '''Process a single request, respecting the concurrency limit.'''
        async with self._concurrency.semaphore:
            try:
                result = await self.handle_request(request)
            except (ProtocolError, RPCError) as e:
                result = e
            except CancelledError:
                raise
            except Exception:
                self.logger.exception(f'exception handling {request}')
                result = RPCError(JSONRPC.INTERNAL_ERROR,
                                  'internal server error')
            if isinstance(request, Request):
                message = request.send_result(result)
                if message:
                    await self._send_message(message)
            if isinstance(result, Exception):
                self._bump_errors()

    def connection_lost(self, exc):
        # Cancel pending requests and message processing
        self.connection.cancel_pending_requests()
        super().connection_lost(exc)

    # External API
    def default_connection(self):
        '''Return a default connection if the user provides none.'''
        return JSONRPCConnection(JSONRPCv2)

    def default_framer(self):
        '''Return a default framer.'''
        return NewlineFramer()

    async def handle_request(self, request):
        pass

    async def send_request(self, method, args=()):
        '''Send an RPC request over the network.'''
        message, event = self.connection.send_request(Request(method, args))
        await self._send_message(message)
        await event.wait()
        result = event.result
        if isinstance(result, Exception):
            raise result
        return result

    async def send_notification(self, method, args=()):
        '''Send an RPC notification over the network.'''
        message = self.connection.send_notification(Notification(method, args))
        await self._send_message(message)

    def send_batch(self, raise_errors=False):
        '''Return a BatchRequest.  Intended to be used like so:

           async with session.send_batch() as batch:
               batch.add_request("method1")
               batch.add_request("sum", (x, y))
               batch.add_notification("updated")

           for result in batch.results:
              ...

        Note that in some circumstances exceptions can be raised; see
        BatchRequest doc string.
        '''
        return BatchRequest(self, raise_errors)


class Server(object):
    '''A simple wrapper around an asyncio.Server object.'''

    def __init__(self, session_factory, host=None, port=None, *,
                 loop=None, **kwargs):
        self.host = host
        self.port = port
        self.loop = loop or asyncio.get_event_loop()
        self.server = None
        self._session_factory = session_factory
        self._kwargs = kwargs

    async def listen(self):
        self.server = await self.loop.create_server(
            self._session_factory, self.host, self.port, **self._kwargs)

    async def close(self):
        '''Close the listening socket.  This does not close any ServerSession
        objects created to handle incoming connections.
        '''
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
