class ErrorCodeException(Exception):
    pass


class UnknownAPIMethodError(ErrorCodeException):
    pass


class RPCError(ErrorCodeException):
    code = 0


class PriceDisagreementError(ErrorCodeException):
    pass


class DuplicateStreamHashError(ErrorCodeException):
    pass


class DownloadCancelledError(ErrorCodeException):
    pass


class DownloadSDTimeout(ErrorCodeException):
    def __init__(self, download):
        super().__init__(f'Failed to download sd blob {download} within timeout')
        self.download = download


class DownloadTimeoutError(ErrorCodeException):
    def __init__(self, download):
        super().__init__(f'Failed to download {download} within timeout')
        self.download = download


class DownloadDataTimeout(ErrorCodeException):
    def __init__(self, download):
        super().__init__(f'Failed to download data blobs for sd hash {download} within timeout')
        self.download = download


class ResolveTimeout(ErrorCodeException):
    def __init__(self, uri):
        super().__init__(f'Failed to resolve "{uri}" within the timeout')
        self.uri = uri


class RequestCanceledError(ErrorCodeException):
    pass


class NegativeFundsError(ErrorCodeException):
    pass


class NullFundsError(ErrorCodeException):
    pass


class InsufficientFundsError(RPCError):
    code = -310


class CurrencyConversionError(ErrorCodeException):
    pass


class FileOpenError(ErrorCodeException):
    # this extends ValueError because it is replacing a ValueError in EncryptedFileDownloader
    # and I don't know where it might get caught upstream
    pass


class ResolveError(ErrorCodeException):
    pass


class ConnectionClosedBeforeResponseError(ErrorCodeException):
    pass


class KeyFeeAboveMaxAllowed(ErrorCodeException):
    pass


class InvalidExchangeRateResponse(ErrorCodeException):
    def __init__(self, source, reason):
        super().__init__(f'Failed to get exchange rate from {source}:{reason}')
        self.source = source
        self.reason = reason


class UnknownNameError(ErrorCodeException):
    def __init__(self, name):
        super().__init__(f'Name {name} is unknown')
        self.name = name


class UnknownClaimID(ErrorCodeException):
    def __init__(self, claim_id):
        super().__init__(f'Claim {claim_id} is unknown')
        self.claim_id = claim_id


class UnknownURI(ErrorCodeException):
    def __init__(self, uri):
        super().__init__(f'URI {uri} cannot be resolved')
        self.name = uri


class UnknownOutpoint(ErrorCodeException):
    def __init__(self, outpoint):
        super().__init__(f'Outpoint {outpoint} cannot be resolved')
        self.outpoint = outpoint


class InvalidName(ErrorCodeException):
    def __init__(self, name, invalid_characters):
        self.name = name
        self.invalid_characters = invalid_characters
        super().__init__(
            'URI contains invalid characters: {}'.format(','.join(invalid_characters)))


class UnknownStreamTypeError(ErrorCodeException):
    def __init__(self, stream_type):
        self.stream_type = stream_type

    def __str__(self):
        return repr(self.stream_type)


class InvalidStreamDescriptorError(ErrorCodeException):
    pass


class InvalidStreamInfoError(ErrorCodeException):
    def __init__(self, name, stream_info):
        msg = f'{name} has claim with invalid stream info: {stream_info}'
        super().__init__(msg)
        self.name = name
        self.stream_info = stream_info


class MisbehavingPeerError(ErrorCodeException):
    pass


class InvalidDataError(MisbehavingPeerError):
    pass


class NoResponseError(MisbehavingPeerError):
    pass


class InvalidResponseError(MisbehavingPeerError):
    pass


class NoSuchBlobError(ErrorCodeException):
    pass


class NoSuchStreamHash(ErrorCodeException):
    pass


class NoSuchSDHash(ErrorCodeException):
    """
    Raised if sd hash is not known
    """


class InvalidBlobHashError(ErrorCodeException):
    pass


class InvalidHeaderError(ErrorCodeException):
    pass


class InvalidAuthenticationToken(ErrorCodeException):
    pass


class NegotiationError(ErrorCodeException):
    pass


class InvalidCurrencyError(ErrorCodeException):
    def __init__(self, currency):
        self.currency = currency
        super().__init__(
            f'Invalid currency: {currency} is not a supported currency.')


class NoSuchDirectoryError(ErrorCodeException):
    def __init__(self, directory):
        self.directory = directory
        super().__init__(f'No such directory {directory}')


class ComponentStartConditionNotMet(ErrorCodeException):
    pass


class ComponentsNotStarted(ErrorCodeException):
    pass
