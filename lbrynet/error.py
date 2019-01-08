class RPCError(Exception):
    code = 0


class PriceDisagreementError(Exception):
    pass


class DuplicateStreamHashError(Exception):
    pass


class DownloadCancelledError(Exception):
    pass


class DownloadSDTimeout(Exception):
    def __init__(self, download):
        super().__init__(f'Failed to download sd blob {download} within timeout')
        self.download = download


class DownloadTimeoutError(Exception):
    def __init__(self, download):
        super().__init__(f'Failed to download {download} within timeout')
        self.download = download


class DownloadDataTimeout(Exception):
    def __init__(self, download):
        super().__init__('Failed to download data blobs for sd hash '
                                 '{} within timeout'.format(download))
        self.download = download


class RequestCanceledError(Exception):
    pass


class NegativeFundsError(Exception):
    pass


class NullFundsError(Exception):
    pass


class InsufficientFundsError(RPCError):
    code = -310


class CurrencyConversionError(Exception):
    pass


class FileOpenError(ValueError):
    # this extends ValueError because it is replacing a ValueError in EncryptedFileDownloader
    # and I don't know where it might get caught upstream
    pass


class ResolveError(Exception):
    pass


class ConnectionClosedBeforeResponseError(Exception):
    pass


class KeyFeeAboveMaxAllowed(Exception):
    pass


class InvalidExchangeRateResponse(Exception):
    def __init__(self, source, reason):
        super().__init__(f'Failed to get exchange rate from {source}:{reason}')
        self.source = source
        self.reason = reason


class UnknownNameError(Exception):
    def __init__(self, name):
        super().__init__(f'Name {name} is unknown')
        self.name = name


class UnknownClaimID(Exception):
    def __init__(self, claim_id):
        super().__init__(f'Claim {claim_id} is unknown')
        self.claim_id = claim_id


class UnknownURI(Exception):
    def __init__(self, uri):
        super().__init__(f'URI {uri} cannot be resolved')
        self.name = uri


class UnknownOutpoint(Exception):
    def __init__(self, outpoint):
        super().__init__(f'Outpoint {outpoint} cannot be resolved')
        self.outpoint = outpoint


class InvalidName(Exception):
    def __init__(self, name, invalid_characters):
        self.name = name
        self.invalid_characters = invalid_characters
        super().__init__(
            'URI contains invalid characters: {}'.format(','.join(invalid_characters)))


class UnknownStreamTypeError(Exception):
    def __init__(self, stream_type):
        self.stream_type = stream_type

    def __str__(self):
        return repr(self.stream_type)


class InvalidStreamDescriptorError(Exception):
    pass


class InvalidStreamInfoError(Exception):
    def __init__(self, name, stream_info):
        msg = f'{name} has claim with invalid stream info: {stream_info}'
        super().__init__(msg)
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


class NoSuchStreamHash(Exception):
    pass


class NoSuchSDHash(Exception):
    """
    Raised if sd hash is not known
    """


class InvalidBlobHashError(Exception):
    pass


class InvalidHeaderError(Exception):
    pass


class InvalidAuthenticationToken(Exception):
    pass


class NegotiationError(Exception):
    pass


class InvalidCurrencyError(Exception):
    def __init__(self, currency):
        self.currency = currency
        super().__init__(
            f'Invalid currency: {currency} is not a supported currency.')


class NoSuchDirectoryError(Exception):
    def __init__(self, directory):
        self.directory = directory
        super().__init__(f'No such directory {directory}')


class ComponentStartConditionNotMet(Exception):
    pass


class ComponentsNotStarted(Exception):
    pass


class BlobDownloadError(Exception):
    pass
