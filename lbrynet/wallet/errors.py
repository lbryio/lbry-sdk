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


class NotEnoughFunds(Exception):
    pass


class InvalidPassword(Exception):
    def __str__(self):
        return "Incorrect password"


class Timeout(Exception):
    pass


class InvalidProofError(Exception):
    pass


class ChainValidationError(Exception):
    pass


class InvalidClaimId(Exception):
    pass
