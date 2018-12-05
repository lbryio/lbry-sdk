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

'''SOCKS proxying.'''

import sys
import asyncio
import collections
import ipaddress
import socket
import struct
from functools import partial


__all__ = ('SOCKSUserAuth', 'SOCKS4', 'SOCKS4a', 'SOCKS5', 'SOCKSProxy',
           'SOCKSError', 'SOCKSProtocolError', 'SOCKSFailure')


SOCKSUserAuth = collections.namedtuple("SOCKSUserAuth", "username password")


class SOCKSError(Exception):
    '''Base class for SOCKS exceptions.  Each raised exception will be
    an instance of a derived class.'''


class SOCKSProtocolError(SOCKSError):
    '''Raised when the proxy does not follow the SOCKS protocol'''


class SOCKSFailure(SOCKSError):
    '''Raised when the proxy refuses or fails to make a connection'''


class NeedData(Exception):
    pass


class SOCKSBase(object):

    @classmethod
    def name(cls):
        return cls.__name__

    def __init__(self):
        self._buffer = bytes()
        self._state = self._start

    def _read(self, size):
        if len(self._buffer) < size:
            raise NeedData(size - len(self._buffer))
        result = self._buffer[:size]
        self._buffer = self._buffer[size:]
        return result

    def receive_data(self, data):
        self._buffer += data

    def next_message(self):
        return self._state()


class SOCKS4(SOCKSBase):
    '''SOCKS4 protocol wrapper.'''

    # See http://ftp.icm.edu.pl/packages/socks/socks4/SOCKS4.protocol
    REPLY_CODES = {
        90: 'request granted',
        91: 'request rejected or failed',
        92: ('request rejected because SOCKS server cannot connect '
             'to identd on the client'),
        93: ('request rejected because the client program and identd '
             'report different user-ids')
    }

    def __init__(self, dst_host, dst_port, auth):
        super().__init__()
        self._dst_host = self._check_host(dst_host)
        self._dst_port = dst_port
        self._auth = auth

    @classmethod
    def _check_host(cls, host):
        if not isinstance(host, ipaddress.IPv4Address):
            try:
                host = ipaddress.IPv4Address(host)
            except ValueError:
                raise SOCKSProtocolError(
                    f'SOCKS4 requires an IPv4 address: {host}') from None
        return host

    def _start(self):
        self._state = self._first_response

        if isinstance(self._dst_host, ipaddress.IPv4Address):
            # SOCKS4
            dst_ip_packed = self._dst_host.packed
            host_bytes = b''
        else:
            # SOCKS4a
            dst_ip_packed = b'\0\0\0\1'
            host_bytes = self._dst_host.encode() + b'\0'

        if isinstance(self._auth, SOCKSUserAuth):
            user_id = self._auth.username.encode()
        else:
            user_id = b''

        # Send TCP/IP stream CONNECT request
        return b''.join([b'\4\1', struct.pack('>H', self._dst_port),
                         dst_ip_packed, user_id, b'\0', host_bytes])

    def _first_response(self):
        # Wait for 8-byte response
        data = self._read(8)
        if data[0] != 0:
            raise SOCKSProtocolError(f'invalid {self.name()} proxy '
                                     f'response: {data}')
        reply_code = data[1]
        if reply_code != 90:
            msg = self.REPLY_CODES.get(
                reply_code, f'unknown {self.name()} reply code {reply_code}')
            raise SOCKSFailure(f'{self.name()} proxy request failed: {msg}')

        # Other fields ignored
        return None


class SOCKS4a(SOCKS4):

    @classmethod
    def _check_host(cls, host):
        if not isinstance(host, (str, ipaddress.IPv4Address)):
            raise SOCKSProtocolError(
                f'SOCKS4a requires an IPv4 address or host name: {host}')
        return host


class SOCKS5(SOCKSBase):
    '''SOCKS protocol wrapper.'''

    # See https://tools.ietf.org/html/rfc1928
    ERROR_CODES = {
        1: 'general SOCKS server failure',
        2: 'connection not allowed by ruleset',
        3: 'network unreachable',
        4: 'host unreachable',
        5: 'connection refused',
        6: 'TTL expired',
        7: 'command not supported',
        8: 'address type not supported',
    }

    def __init__(self, dst_host, dst_port, auth):
        super().__init__()
        self._dst_bytes = self._destination_bytes(dst_host, dst_port)
        self._auth_bytes, self._auth_methods = self._authentication(auth)

    def _destination_bytes(self, host, port):
        if isinstance(host, ipaddress.IPv4Address):
            addr_bytes = b'\1' + host.packed
        elif isinstance(host, ipaddress.IPv6Address):
            addr_bytes = b'\4' + host.packed
        elif isinstance(host, str):
            host = host.encode()
            if len(host) > 255:
                raise SOCKSProtocolError(f'hostname too long: '
                                         f'{len(host)} bytes')
            addr_bytes = b'\3' + bytes([len(host)]) + host
        else:
            raise SOCKSProtocolError(f'SOCKS5 requires an IPv4 address, IPv6 '
                                     f'address, or host name: {host}')
        return addr_bytes + struct.pack('>H', port)

    def _authentication(self, auth):
        if isinstance(auth, SOCKSUserAuth):
            user_bytes = auth.username.encode()
            if not 0 < len(user_bytes) < 256:
                raise SOCKSProtocolError(f'username {auth.username} has '
                                         f'invalid length {len(user_bytes)}')
            pwd_bytes = auth.password.encode()
            if not 0 < len(pwd_bytes) < 256:
                raise SOCKSProtocolError(f'password has invalid length '
                                         f'{len(pwd_bytes)}')
            return b''.join([bytes([1, len(user_bytes)]), user_bytes,
                            bytes([len(pwd_bytes)]), pwd_bytes]), [0, 2]
        return b'', [0]

    def _start(self):
        self._state = self._first_response
        return (b'\5' + bytes([len(self._auth_methods)])
                + bytes(m for m in self._auth_methods))

    def _first_response(self):
        # Wait for 2-byte response
        data = self._read(2)
        if data[0] != 5:
            raise SOCKSProtocolError(f'invalid SOCKS5 proxy response: {data}')
        if data[1] not in self._auth_methods:
            raise SOCKSFailure('SOCKS5 proxy rejected authentication methods')

        # Authenticate if user-password authentication
        if data[1] == 2:
            self._state = self._auth_response
            return self._auth_bytes
        return self._request_connection()

    def _auth_response(self):
        data = self._read(2)
        if data[0] != 1:
            raise SOCKSProtocolError(f'invalid SOCKS5 proxy auth '
                                     f'response: {data}')
        if data[1] != 0:
            raise SOCKSFailure(f'SOCKS5 proxy auth failure code: '
                               f'{data[1]}')

        return self._request_connection()

    def _request_connection(self):
        # Send connection request
        self._state = self._connect_response
        return b'\5\1\0' + self._dst_bytes

    def _connect_response(self):
        data = self._read(5)
        if data[0] != 5 or data[2] != 0 or data[3] not in (1, 3, 4):
            raise SOCKSProtocolError(f'invalid SOCKS5 proxy response: {data}')
        if data[1] != 0:
            raise SOCKSFailure(self.ERROR_CODES.get(
                data[1], f'unknown SOCKS5 error code: {data[1]}'))

        if data[3] == 1:
            addr_len = 3   # IPv4
        elif data[3] == 3:
            addr_len = data[4]  # Hostname
        else:
            addr_len = 15  # IPv6

        self._state = partial(self._connect_response_rest, addr_len)
        return self.next_message()

    def _connect_response_rest(self, addr_len):
        self._read(addr_len + 2)
        return None


class SOCKSProxy(object):

    def __init__(self, address, protocol, auth):
        '''A SOCKS proxy at an address following a SOCKS protocol.  auth is an
        authentication method to use when connecting, or None.

        address is a (host, port) pair; for IPv6 it can instead be a
        (host, port, flowinfo, scopeid) 4-tuple.
        '''
        self.address = address
        self.protocol = protocol
        self.auth = auth
        # Set on each successful connection via the proxy to the
        # result of socket.getpeername()
        self.peername = None

    def __str__(self):
        auth = 'username' if self.auth else 'none'
        return f'{self.protocol.name()} proxy at {self.address}, auth: {auth}'

    async def _handshake(self, client, sock, loop):
        while True:
            count = 0
            try:
                message = client.next_message()
            except NeedData as e:
                count = e.args[0]
            else:
                if message is None:
                    return
                await loop.sock_sendall(sock, message)

            if count:
                data = await loop.sock_recv(sock, count)
                if not data:
                    raise SOCKSProtocolError("EOF received")
                client.receive_data(data)

    async def _connect_one(self, host, port):
        '''Connect to the proxy and perform a handshake requesting a
        connection to (host, port).

        Return the open socket on success, or the exception on failure.
        '''
        client = self.protocol(host, port, self.auth)
        sock = socket.socket()
        loop = asyncio.get_event_loop()
        try:
            # A non-blocking socket is required by loop socket methods
            sock.setblocking(False)
            await loop.sock_connect(sock, self.address)
            await self._handshake(client, sock, loop)
            self.peername = sock.getpeername()
            return sock
        except Exception as e:
            # Don't close - see https://github.com/kyuupichan/aiorpcX/issues/8
            if sys.platform.startswith('linux'):
                sock.close()
            return e

    async def _connect(self, addresses):
        '''Connect to the proxy and perform a handshake requesting a
        connection to each address in addresses.

        Return an (open_socket, address) pair on success.
        '''
        assert len(addresses) > 0

        exceptions = []
        for address in addresses:
            host, port = address[:2]
            sock = await self._connect_one(host, port)
            if isinstance(sock, socket.socket):
                return sock, address
            exceptions.append(sock)

        strings = set(f'{exc!r}' for exc in exceptions)
        raise (exceptions[0] if len(strings) == 1 else
               OSError(f'multiple exceptions: {", ".join(strings)}'))

    async def _detect_proxy(self):
        '''Return True if it appears we can connect to a SOCKS proxy,
        otherwise False.
        '''
        if self.protocol is SOCKS4a:
            host, port = 'www.apple.com', 80
        else:
            host, port = ipaddress.IPv4Address('8.8.8.8'), 53

        sock = await self._connect_one(host, port)
        if isinstance(sock, socket.socket):
            sock.close()
            return True

        # SOCKSFailure indicates something failed, but that we are
        # likely talking to a proxy
        return isinstance(sock, SOCKSFailure)

    @classmethod
    async def auto_detect_address(cls, address, auth):
        '''Try to detect a SOCKS proxy at address using the authentication
        method (or None).  SOCKS5, SOCKS4a and SOCKS are tried in
        order.  If a SOCKS proxy is detected a SOCKSProxy object is
        returned.

        Returning a SOCKSProxy does not mean it is functioning - for
        example, it may have no network connectivity.

        If no proxy is detected return None.
        '''
        for protocol in (SOCKS5, SOCKS4a, SOCKS4):
            proxy = cls(address, protocol, auth)
            if await proxy._detect_proxy():
                return proxy
        return None

    @classmethod
    async def auto_detect_host(cls, host, ports, auth):
        '''Try to detect a SOCKS proxy on a host on one of the ports.

        Calls auto_detect for the ports in order.  Returns SOCKS are
        tried in order; a SOCKSProxy object for the first detected
        proxy is returned.

        Returning a SOCKSProxy does not mean it is functioning - for
        example, it may have no network connectivity.

        If no proxy is detected return None.
        '''
        for port in ports:
            address = (host, port)
            proxy = await cls.auto_detect_address(address, auth)
            if proxy:
                return proxy

        return None

    async def create_connection(self, protocol_factory, host, port, *,
                                resolve=False, ssl=None,
                                family=0, proto=0, flags=0):
        '''Set up a connection to (host, port) through the proxy.

        If resolve is True then host is resolved locally with
        getaddrinfo using family, proto and flags, otherwise the proxy
        is asked to resolve host.

        The function signature is similar to loop.create_connection()
        with the same result.  The attribute _address is set on the
        protocol to the address of the successful remote connection.
        Additionally raises SOCKSError if something goes wrong with
        the proxy handshake.
        '''
        loop = asyncio.get_event_loop()
        if resolve:
            infos = await loop.getaddrinfo(host, port, family=family,
                                           type=socket.SOCK_STREAM,
                                           proto=proto, flags=flags)
            addresses = [info[4] for info in infos]
        else:
            addresses = [(host, port)]

        sock, address = await self._connect(addresses)

        def set_address():
            protocol = protocol_factory()
            protocol._address = address
            return protocol

        return await loop.create_connection(
            set_address, sock=sock, ssl=ssl,
            server_hostname=host if ssl else None)
