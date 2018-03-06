class TransportException(Exception):
    pass


class ServiceException(Exception):
    code = -2


class RemoteServiceException(Exception):
    pass


class ProtocolException(Exception):
    pass


class MethodNotFoundException(ServiceException):
    code = -3
