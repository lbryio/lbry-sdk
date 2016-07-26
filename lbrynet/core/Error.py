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


class KeyFeeAboveMaxAllowed(Exception):
    pass


class UnknownNameError(Exception):
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return repr(self.name)


class UnknownStreamTypeError(Exception):
    def __init__(self, stream_type):
        self.stream_type = stream_type

    def __str__(self):
        return repr(self.stream_type)


class InvalidStreamDescriptorError(Exception):
    pass


class InvalidStreamInfoError(Exception):
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return repr(self.name)


class MisbehavingPeerError(Exception):
    pass


class InvalidDataError(MisbehavingPeerError):
    pass


class NoResponseError(MisbehavingPeerError):
    pass


class InvalidResponseError(MisbehavingPeerError):
    pass


class NoSuchBlobError(Exception):
    pass


class NoSuchStreamHashError(Exception):
    pass


class InvalidBlobHashError(Exception):
    pass