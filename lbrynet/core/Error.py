class PriceDisagreementError(Exception):
    pass


class DuplicateStreamHashError(Exception):
    pass


class DownloadCanceledError(Exception):
    pass


class RequestCanceledError(Exception):
    pass


class InsufficientFundsError(Exception):
    pass


class ConnectionClosedBeforeResponseError(Exception):
    pass


class UnknownNameError(Exception):
    def __init__(self, name):
        self.name = name


class InvalidStreamInfoError(Exception):
    def __init__(self, name):
        self.name = name


class MisbehavingPeerError(Exception):
    pass


class InvalidDataError(MisbehavingPeerError):
    pass


class NoResponseError(MisbehavingPeerError):
    pass


class InvalidResponseError(MisbehavingPeerError):
    pass