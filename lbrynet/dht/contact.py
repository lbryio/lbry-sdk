import ipaddress
from binascii import hexlify
from functools import reduce
from lbrynet.dht import constants


def is_valid_ipv4(address):
    try:
        ip = ipaddress.ip_address(address)
        return ip.version == 4
    except ipaddress.AddressValueError:
        return False


class _Contact:
    """ Encapsulation for remote contact

    This class contains information on a single remote contact, and also
    provides a direct RPC API to the remote node which it represents
    """

    def __init__(self, contactManager, id, ipAddress, udpPort, networkProtocol, firstComm):
        if id is not None:
            if not len(id) == constants.key_bits // 8:
                raise ValueError("invalid node id: {}".format(hexlify(id).decode()))
        if not 0 <= udpPort <= 65536:
            raise ValueError("invalid port")
        if not is_valid_ipv4(ipAddress):
            raise ValueError("invalid ip address")
        self._contactManager = contactManager
        self._id = id
        self.address = ipAddress
        self.port = udpPort
        self._networkProtocol = networkProtocol
        self.commTime = firstComm
        self.getTime = self._contactManager._get_time
        self.lastReplied = None
        self.lastRequested = None
        self.protocolVersion = 0
        self._token = (None, 0)  # token, timestamp

    def update_token(self, token):
        self._token = token, self.getTime()

    @property
    def token(self):
        # expire the token 1 minute early to be safe
        return self._token[0] if self._token[1] + 240 > self.getTime() else None

    @property
    def lastInteracted(self):
        return max(self.lastRequested or 0, self.lastReplied or 0, self.lastFailed or 0)

    @property
    def id(self):
        return self._id

    def log_id(self, short=True):
        if not self.id:
            return "not initialized"
        id_hex = hexlify(self.id)
        return id_hex if not short else id_hex[:8]

    @property
    def failedRPCs(self):
        return len(self.failures)

    @property
    def lastFailed(self):
        return self._contactManager._rpc_failures.get((self.address, self.port), [None])[-1]

    @property
    def failures(self):
        return self._contactManager._rpc_failures.get((self.address, self.port), [])

    @property
    def contact_is_good(self):
        """
        :return: False if contact is bad, None if contact is unknown, or True if contact is good
        """
        failures = self.failures
        now = self.getTime()
        delay = constants.checkRefreshInterval

        if failures:
            if self.lastReplied and len(failures) >= 2 and self.lastReplied < failures[-2]:
                return False
            elif self.lastReplied and len(failures) >= 2 and self.lastReplied > failures[-2]:
                pass  # handled below
            elif len(failures) >= 2:
                return False

        if self.lastReplied and self.lastReplied > now - delay:
            return True
        if self.lastReplied and self.lastRequested and self.lastRequested > now - delay:
            return True
        return None

    def __eq__(self, other):
        if not isinstance(other, _Contact):
            raise TypeError("invalid type to compare with Contact: %s" % str(type(other)))
        return (self.id, self.address, self.port) == (other.id, other.address, other.port)

    def __hash__(self):
        return hash((self.id, self.address, self.port))

    def compact_ip(self):
        compact_ip = reduce(
            lambda buff, x: buff + bytearray([int(x)]), self.address.split('.'), bytearray())
        return compact_ip

    def set_id(self, id):
        if not self._id:
            self._id = id

    def update_last_replied(self):
        self.lastReplied = int(self.getTime())

    def update_last_requested(self):
        self.lastRequested = int(self.getTime())

    def update_last_failed(self):
        failures = self._contactManager._rpc_failures.get((self.address, self.port), [])
        failures.append(self.getTime())
        self._contactManager._rpc_failures[(self.address, self.port)] = failures

    def update_protocol_version(self, version):
        self.protocolVersion = version

    def __str__(self):
        return '<%s.%s object; IP address: %s, UDP port: %d>' % (
            self.__module__, self.__class__.__name__, self.address, self.port)

    def __getattr__(self, name):
        """ This override allows the host node to call a method of the remote
        node (i.e. this contact) as if it was a local function.

        For instance, if C{remoteNode} is a instance of C{Contact}, the
        following will result in C{remoteNode}'s C{test()} method to be
        called with argument C{123}::
         remoteNode.test(123)

        Such a RPC method call will return a Deferred, which will callback
        when the contact responds with the result (or an error occurs).
        This happens via this contact's C{_networkProtocol} object (i.e. the
        host Node's C{_protocol} object).
        """

        if name not in ['ping', 'findValue', 'findNode', 'store']:
            raise AttributeError("unknown command: %s" % name)

        def _sendRPC(*args, **kwargs):
            return self._networkProtocol.sendRPC(self, name.encode(), args)

        return _sendRPC


class ContactManager:
    def __init__(self, get_time=None):
        if not get_time:
            from twisted.internet import reactor
            get_time = reactor.seconds
        self._get_time = get_time
        self._contacts = {}
        self._rpc_failures = {}

    def get_contact(self, id, address, port):
        for contact in self._contacts.values():
            if contact.id == id and contact.address == address and contact.port == port:
                return contact

    def make_contact(self, id, ipAddress, udpPort, networkProtocol, firstComm=0):
        contact = self.get_contact(id, ipAddress, udpPort)
        if contact:
            return contact
        contact = _Contact(self, id, ipAddress, udpPort, networkProtocol, firstComm or self._get_time())
        self._contacts[(id, ipAddress, udpPort)] = contact
        return contact

    def is_ignored(self, origin_tuple):
        failed_rpc_count = len(self._prune_failures(origin_tuple))
        return failed_rpc_count > constants.rpcAttempts

    def _prune_failures(self, origin_tuple):
        # Prunes recorded failures to the last time window of attempts
        pruning_limit = self._get_time() - constants.rpcAttemptsPruningTimeWindow
        pruned = list(filter(lambda t: t >= pruning_limit, self._rpc_failures.get(origin_tuple, [])))
        self._rpc_failures[origin_tuple] = pruned
        return pruned
