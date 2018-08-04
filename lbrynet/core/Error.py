class RPCError(Exception):
    code = 0


class PriceDisagreementError(Exception):
    pass


class DuplicateStreamHashError(Exception):
    pass


class DownloadCanceledError(Exception):
    pass


class DownloadSDTimeout(Exception):
    def __init__(self, download):
        super().__init__('Failed to download sd blob {} within timeout'.format(download))
        self.download = download


class DownloadTimeoutError(Exception):
    def __init__(self, download):
        super().__init__('Failed to download {} within timeout'.format(download))
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


class ConnectionClosedBeforeResponseError(Exception):
    pass


class KeyFeeAboveMaxAllowed(Exception):
    pass


class InvalidExchangeRateResponse(Exception):
    def __init__(self, source, reason):
        super().__init__('Failed to get exchange rate from {}:{}'.format(source, reason))
        self.source = source
        self.reason = reason


class UnknownNameError(Exception):
    def __init__(self, name):
        super().__init__('Name {} is unknown'.format(name))
        self.name = name


class UnknownClaimID(Exception):
    def __init__(self, claim_id):
        super().__init__('Claim {} is unknown'.format(claim_id))
        self.claim_id = claim_id


class UnknownURI(Exception):
    def __init__(self, uri):
        super().__init__('URI {} cannot be resolved'.format(uri))
        self.name = uri


class UnknownOutpoint(Exception):
    def __init__(self, outpoint):
        super().__init__('Outpoint {} cannot be resolved'.format(outpoint))
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
        msg = '{} has claim with invalid stream info: {}'.format(name, stream_info)
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
            'Invalid currency: {} is not a supported currency.'.format(currency))


class NoSuchDirectoryError(Exception):
    def __init__(self, directory):
        self.directory = directory
        super().__init__('No such directory {}'.format(directory))


class ComponentStartConditionNotMet(Exception):
    pass


class ComponentsNotStarted(Exception):
    pass
