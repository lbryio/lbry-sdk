class BaseKademliaException(Exception):
    pass


class DecodeError(BaseKademliaException):
    """
    Should be raised by an C{Encoding} implementation if decode operation
    fails
    """
    pass


class BucketFull(BaseKademliaException):
    """
    Raised when the bucket is full
    """
    pass


class UnknownRemoteException(BaseKademliaException):
    pass


class TransportNotConnected(BaseKademliaException):
    pass
