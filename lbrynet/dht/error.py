import binascii
#import exceptions

# this is a dict of {"exceptions.<exception class name>": exception class} items used to raise
# remote built-in exceptions locally
BUILTIN_EXCEPTIONS = {
#    "exceptions.%s" % e: getattr(exceptions, e) for e in dir(exceptions) if not e.startswith("_")
}


class DecodeError(Exception):
    """
    Should be raised by an C{Encoding} implementation if decode operation
    fails
    """
    pass


class BucketFull(Exception):
    """
    Raised when the bucket is full
    """
    pass


class UnknownRemoteException(Exception):
    pass


class TimeoutError(Exception):
    """ Raised when a RPC times out """

    def __init__(self, remote_contact_id):
        # remote_contact_id is a binary blob so we need to convert it
        # into something more readable
        if remote_contact_id:
            msg = 'Timeout connecting to {}'.format(binascii.hexlify(remote_contact_id))
        else:
            msg = 'Timeout connecting to uninitialized node'
        Exception.__init__(self, msg)
        self.remote_contact_id = remote_contact_id


class TransportNotConnected(Exception):
    pass
