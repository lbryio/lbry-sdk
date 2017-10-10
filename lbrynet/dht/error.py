import binascii


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
        msg = 'Timeout connecting to {}'.format(binascii.hexlify(remote_contact_id))
        Exception.__init__(self, msg)
        self.remote_contact_id = remote_contact_id
