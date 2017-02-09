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
        Exception.__init__(self, 'Name {} is unknown'.format(name))
        self.name = name


class InvalidName(Exception):
    def __init__(self, name, invalid_characters):
        self.name = name
        self.invalid_characters = invalid_characters
        Exception.__init__(
            self, 'URI contains invalid characters: {}'.format(','.join(invalid_characters)))


class UnknownStreamTypeError(Exception):
    def __init__(self, stream_type):
        self.stream_type = stream_type

    def __str__(self):
        return repr(self.stream_type)


class InvalidStreamDescriptorError(Exception):
    pass


class InvalidStreamInfoError(Exception):
    def __init__(self, name, stream_info):
        msg = '{} has claim with invalid stream info: {}'.format(name, stream_info)
        Exception.__init__(self, msg)
        self.name = name
        self.stream_info = stream_info


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


class InvalidHeaderError(Exception):
    pass


class InvalidAuthenticationToken(Exception):
    pass


class NegotiationError(Exception):
    pass
