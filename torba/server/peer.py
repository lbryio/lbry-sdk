# Copyright (c) 2017, Neil Booth
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

'''Representation of a peer server.'''

from ipaddress import ip_address

from torba.server import util
from torba.server.util import cachedproperty

from typing import Dict


class Peer:

    # Protocol version
    ATTRS = ('host', 'features',
             # metadata
             'source', 'ip_addr',
             'last_good', 'last_try', 'try_count')
    FEATURES = ('pruning', 'server_version', 'protocol_min', 'protocol_max',
                'ssl_port', 'tcp_port')
    # This should be set by the application
    DEFAULT_PORTS: Dict[str, int] = {}

    def __init__(self, host, features, source='unknown', ip_addr=None,
                 last_good=0, last_try=0, try_count=0):
        '''Create a peer given a host name (or IP address as a string),
        a dictionary of features, and a record of the source.'''
        assert isinstance(host, str)
        assert isinstance(features, dict)
        assert host in features.get('hosts', {})
        self.host = host
        self.features = features.copy()
        # Canonicalize / clean-up
        for feature in self.FEATURES:
            self.features[feature] = getattr(self, feature)
        # Metadata
        self.source = source
        self.ip_addr = ip_addr
        # last_good represents the last connection that was
        # successful *and* successfully verified, at which point
        # try_count is set to 0.  Failure to connect or failure to
        # verify increment the try_count.
        self.last_good = last_good
        self.last_try = last_try
        self.try_count = try_count
        # Transient, non-persisted metadata
        self.bad = False
        self.other_port_pairs = set()

    @classmethod
    def peers_from_features(cls, features, source):
        peers = []
        if isinstance(features, dict):
            hosts = features.get('hosts')
            if isinstance(hosts, dict):
                peers = [Peer(host, features, source=source)
                         for host in hosts if isinstance(host, str)]
        return peers

    @classmethod
    def deserialize(cls, item):
        '''Deserialize from a dictionary.'''
        return cls(**item)

    def matches(self, peers):
        '''Return peers whose host matches our hostname or IP address.
        Additionally include all peers whose IP address matches our
        hostname if that is an IP address.
        '''
        candidates = (self.host.lower(), self.ip_addr)
        return [peer for peer in peers
                if peer.host.lower() in candidates
                or peer.ip_addr == self.host]

    def __str__(self):
        return self.host

    def update_features(self, features):
        '''Update features in-place.'''
        try:
            tmp = Peer(self.host, features)
        except Exception:
            pass
        else:
            self.update_features_from_peer(tmp)

    def update_features_from_peer(self, peer):
        if peer != self:
            self.features = peer.features
            for feature in self.FEATURES:
                setattr(self, feature, getattr(peer, feature))

    def connection_port_pairs(self):
        '''Return a list of (kind, port) pairs to try when making a
        connection.'''
        # Use a list not a set - it's important to try the registered
        # ports first.
        pairs = [('SSL', self.ssl_port), ('TCP', self.tcp_port)]
        while self.other_port_pairs:
            pairs.append(self.other_port_pairs.pop())
        return [pair for pair in pairs if pair[1]]

    def mark_bad(self):
        '''Mark as bad to avoid reconnects but also to remember for a
        while.'''
        self.bad = True

    def check_ports(self, other):
        '''Remember differing ports in case server operator changed them
        or removed one.'''
        if other.ssl_port != self.ssl_port:
            self.other_port_pairs.add(('SSL', other.ssl_port))
        if other.tcp_port != self.tcp_port:
            self.other_port_pairs.add(('TCP', other.tcp_port))
        return bool(self.other_port_pairs)

    @cachedproperty
    def is_tor(self):
        return self.host.endswith('.onion')

    @cachedproperty
    def is_valid(self):
        ip = self.ip_address
        if ip:
            return ((ip.is_global or ip.is_private)
                    and not (ip.is_multicast or ip.is_unspecified))
        return util.is_valid_hostname(self.host)

    @cachedproperty
    def is_public(self):
        ip = self.ip_address
        if ip:
            return self.is_valid and not ip.is_private
        else:
            return self.is_valid and self.host != 'localhost'

    @cachedproperty
    def ip_address(self):
        '''The host as a python ip_address object, or None.'''
        try:
            return ip_address(self.host)
        except ValueError:
            return None

    def bucket(self):
        if self.is_tor:
            return 'onion'
        if not self.ip_addr:
            return ''
        return tuple(self.ip_addr.split('.')[:2])

    def serialize(self):
        '''Serialize to a dictionary.'''
        return {attr: getattr(self, attr) for attr in self.ATTRS}

    def _port(self, key):
        hosts = self.features.get('hosts')
        if isinstance(hosts, dict):
            host = hosts.get(self.host)
            port = self._integer(key, host)
            if port and 0 < port < 65536:
                return port
        return None

    def _integer(self, key, d=None):
        d = d or self.features
        result = d.get(key) if isinstance(d, dict) else None
        if isinstance(result, str):
            try:
                result = int(result)
            except ValueError:
                pass
        return result if isinstance(result, int) else None

    def _string(self, key):
        result = self.features.get(key)
        return result if isinstance(result, str) else None

    @cachedproperty
    def genesis_hash(self):
        '''Returns None if no SSL port, otherwise the port as an integer.'''
        return self._string('genesis_hash')

    @cachedproperty
    def ssl_port(self):
        '''Returns None if no SSL port, otherwise the port as an integer.'''
        return self._port('ssl_port')

    @cachedproperty
    def tcp_port(self):
        '''Returns None if no TCP port, otherwise the port as an integer.'''
        return self._port('tcp_port')

    @cachedproperty
    def server_version(self):
        '''Returns the server version as a string if known, otherwise None.'''
        return self._string('server_version')

    @cachedproperty
    def pruning(self):
        '''Returns the pruning level as an integer.  None indicates no
        pruning.'''
        pruning = self._integer('pruning')
        if pruning and pruning > 0:
            return pruning
        return None

    def _protocol_version_string(self, key):
        version_str = self.features.get(key)
        ptuple = util.protocol_tuple(version_str)
        return util.version_string(ptuple)

    @cachedproperty
    def protocol_min(self):
        '''Minimum protocol version as a string, e.g., 1.0'''
        return self._protocol_version_string('protocol_min')

    @cachedproperty
    def protocol_max(self):
        '''Maximum protocol version as a string, e.g., 1.1'''
        return self._protocol_version_string('protocol_max')

    def to_tuple(self):
        '''The tuple ((ip, host, details) expected in response
        to a peers subscription.'''
        details = self.real_name().split()[1:]
        return (self.ip_addr or self.host, self.host, details)

    def real_name(self):
        '''Real name of this peer as used on IRC.'''
        def port_text(letter, port):
            if port == self.DEFAULT_PORTS.get(letter):
                return letter
            else:
                return letter + str(port)

        parts = [self.host, 'v' + self.protocol_max]
        if self.pruning:
            parts.append('p{:d}'.format(self.pruning))
        for letter, port in (('s', self.ssl_port), ('t', self.tcp_port)):
            if port:
                parts.append(port_text(letter, port))
        return ' '.join(parts)

    @classmethod
    def from_real_name(cls, real_name, source):
        '''Real name is a real name as on IRC, such as

            "erbium1.sytes.net v1.0 s t"

        Returns an instance of this Peer class.
        '''
        host = 'nohost'
        features = {}
        ports = {}
        for n, part in enumerate(real_name.split()):
            if n == 0:
                host = part
                continue
            if part[0] in ('s', 't'):
                if len(part) == 1:
                    port = cls.DEFAULT_PORTS[part[0]]
                else:
                    port = part[1:]
                if part[0] == 's':
                    ports['ssl_port'] = port
                else:
                    ports['tcp_port'] = port
            elif part[0] == 'v':
                features['protocol_max'] = features['protocol_min'] = part[1:]
            elif part[0] == 'p':
                features['pruning'] = part[1:]

        features.update(ports)
        features['hosts'] = {host: ports}

        return cls(host, features, source)
