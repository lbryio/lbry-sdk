class BaseKademliaException(Exception):
    pass


class DecodeError(BaseKademliaException):
    """
    Should be raised by an C{Encoding} implementation if decode operation
    fails
    """


class BucketFull(BaseKademliaException):
    """
    Raised when the bucket is full
    """


class RemoteException(BaseKademliaException):
    pass


class TransportNotConnected(BaseKademliaException):
    pass
