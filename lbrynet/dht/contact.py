from lbrynet.dht import constants


class _Contact(object):
    """ Encapsulation for remote contact

    This class contains information on a single remote contact, and also
    provides a direct RPC API to the remote node which it represents
    """

    def __init__(self, contactManager, id, ipAddress, udpPort, networkProtocol, firstComm):
        self._contactManager = contactManager
        self._id = id
        if id is not None:
            if not len(id) == constants.key_bits / 8:
                raise ValueError("invalid node id: %s" % id.encode('hex'))
        self.address = ipAddress
        self.port = udpPort
        self._networkProtocol = networkProtocol
        self.commTime = firstComm
        self.getTime = self._contactManager._get_time
        self.lastReplied = None
        self.lastRequested = None

    @property
    def lastInteracted(self):
        return max(self.lastRequested or 0, self.lastReplied or 0, self.lastFailed or 0)

    @property
    def id(self):
        return self._id

    def log_id(self, short=True):
        if not self.id:
            return "not initialized"
        id_hex = self.id.encode('hex')
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
        delay = constants.refreshTimeout / 4

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
        if isinstance(other, _Contact):
            return self.id == other.id
        elif isinstance(other, str):
            return self.id == other
        else:
            return False

    def __ne__(self, other):
        if isinstance(other, _Contact):
            return self.id != other.id
        elif isinstance(other, str):
            return self.id != other
        else:
            return True

    def compact_ip(self):
        compact_ip = reduce(
            lambda buff, x: buff + bytearray([int(x)]), self.address.split('.'), bytearray())
        return str(compact_ip)

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

        def _sendRPC(*args, **kwargs):
            return self._networkProtocol.sendRPC(self, name, args, **kwargs)

        return _sendRPC


class ContactManager(object):
    def __init__(self, get_time=None):
        if not get_time:
            from twisted.internet import reactor
            get_time = reactor.seconds
        self._get_time = get_time
        self._contacts = {}
        self._rpc_failures = {}

    def get_contact(self, id, address, port):
        for contact in self._contacts.itervalues():
            if contact.id == id and contact.address == address and contact.port == port:
                return contact

    def make_contact(self, id, ipAddress, udpPort, networkProtocol, firstComm=0):
        ipAddress = str(ipAddress)
        contact = self.get_contact(id, ipAddress, udpPort)
        if contact:
            return contact
        contact = _Contact(self, id, ipAddress, udpPort, networkProtocol, firstComm or self._get_time())
        self._contacts[(id, ipAddress, udpPort)] = contact
        return contact

    def is_ignored(self, origin_tuple):
        failed_rpc_count = len(self._rpc_failures.get(origin_tuple, []))
        return failed_rpc_count > constants.rpcAttempts
