from .base import BaseError


class InitializationError(BaseError):
    """
    **Daemon `start` and other CLI command failures (non-recoverable)**
    """


class ClientError(InitializationError):
    """
    Error codes reported by clients connecting to `lbrynet` daemon.
    """


class RPCConnectionError(ClientError):
    def __init__(self):
        super().__init__("Failed to establish HTTP connection to `lbrynet`. (Is it running?)")


class RPCUnresponsiveError(ClientError):
    def __init__(self):
        super().__init__("HTTP connection established but daemon is not responding to commands.")


class WebSocketConnectionError(ClientError):
    def __init__(self):
        super().__init__("WebSocket connection established but daemon is not responding to commands.")


class WebSocketUnresponsiveError(ClientError):
    def __init__(self):
        super().__init__("Failed to establish WebSocket connection to `lbrynet`. (Is it running?)")


class HardwareError(InitializationError):
    """
    Enough of `lbrynet` was able to start to determine external factors causing eventual failure.
    """


class OutOfSpaceError(HardwareError):
    def __init__(self):
        super().__init__("Out of disk space.")


class OutOfRAMError(HardwareError):
    def __init__(self):
        super().__init__("Out of RAM.")


class EnvironmentError(InitializationError):
    """
    Internal factors preventing `lbrynet` from bootstrapping itself.
    """


class IncompatiblePythonError(EnvironmentError):
    def __init__(self):
        super().__init__("Incompatible version of Python.")


class IncompatibleDependencyError(EnvironmentError):
    def __init__(self):
        super().__init__("Incompatible version of some library.")


class ConfigurationError(InitializationError):
    """
    Configuration errors.
    """


class CannotWriteConfigurationError(ConfigurationError):
    """
    When writing the default config fails on startup, such as due to permission issues.
    """
    def __init__(self, path):
        super().__init__(f"Cannot write configuration file '{path}'.")


class CannotOpenConfigurationError(ConfigurationError):
    """
    Can't open the config file user provided via command line args.
    """
    def __init__(self, path):
        super().__init__(f"Cannot find provided configuration file '{path}'.")


class CannotParseConfigurationError(ConfigurationError):
    """
    Includes the syntax error / line number to help user fix it.
    """
    def __init__(self, path):
        super().__init__(f"Failed to parse the configuration file '{path}'.")


class ConfigurationMissingError(ConfigurationError):
    def __init__(self, path):
        super().__init__(f"Configuration file '{path}' is missing setting that has no default / fallback.")


class ConfigurationInvalidError(ConfigurationError):
    def __init__(self, path):
        super().__init__(f"Configuration file '{path}' has setting with invalid value.")


class CommandError(InitializationError):
    """
    Errors preparing to execute commands.
    """


class CommandDoesNotExistError(CommandError):
    def __init__(self, command):
        super().__init__(f"Command '{command}' does not exist.")


class CommandDeprecatedError(CommandError):
    def __init__(self, command):
        super().__init__(f"Command '{command}' is deprecated.")


class CommandInvalidArgumentError(CommandError):
    def __init__(self, command):
        super().__init__(f"Invalid arguments for command '{command}'.")


class CommandTemporarilyUnavailableError(CommandError):
    """
    Such as waiting for required components to start.
    """
    def __init__(self, command):
        super().__init__(f"Command '{command}' is temporarily unavailable.")


class CommandPermanentlyUnavailableError(CommandError):
    """
    such as when required component was intentionally configured not to start.
    """
    def __init__(self, command):
        super().__init__(f"Command '{command}' is permanently unavailable.")


class NetworkingError(BaseError):
    """
    **Networking**
    """


class ConnectivityError(NetworkingError):
    """
    General connectivity.
    """


class NoInternetError(ConnectivityError):
    def __init__(self):
        super().__init__("No internet connection.")


class NoUPnPSupportError(ConnectivityError):
    def __init__(self):
        super().__init__("Router does not support UPnP.")


class WalletConnectivityError(NetworkingError):
    """
    Wallet server connectivity.
    """


class WalletConnectionError(WalletConnectivityError):
    """
    Should normally not need to be handled higher up as `lbrynet` will retry other servers.
    """
    def __init__(self):
        super().__init__("Failed connecting to a lbryumx server.")


class WalletConnectionsError(WalletConnectivityError):
    """
    Will need to bubble up and require user to do something.
    """
    def __init__(self):
        super().__init__("Failed connecting to all known lbryumx servers.")


class WalletConnectionDroppedError(WalletConnectivityError):
    """
    Maybe we were being bad?
    """
    def __init__(self):
        super().__init__("lbryumx droppped our connection.")


class WalletDisconnectedError(NetworkingError):
    """
    Wallet connection dropped.
    """


class WalletServerSuspiciousError(WalletDisconnectedError):
    def __init__(self):
        super().__init__("Disconnected from lbryumx server due to suspicious responses. *generic*")


class WalletServerValidationError(WalletDisconnectedError):
    def __init__(self):
        super().__init__("Disconnected from lbryumx server due to SPV validation failure.")


class WalletServerHeaderError(WalletDisconnectedError):
    def __init__(self):
        super().__init__("Disconnected from lbryumx server due to incorrect header received.")


class WalletServerVersionError(WalletDisconnectedError):
    def __init__(self):
        super().__init__("Disconnected from lbryumx server due to incompatible protocol version.")


class WalletServerUnresponsiveError(WalletDisconnectedError):
    def __init__(self):
        super().__init__("Disconnected from lbryumx server due to unresponsiveness.")


class DataConnectivityError(NetworkingError):
    """
    P2P connection errors.
    """


class DataNetworkError(NetworkingError):
    """
    P2P download errors.
    """


class DataDownloadError(DataNetworkError):
    def __init__(self):
        super().__init__("Failed to download blob. *generic*")


class DataUploadError(NetworkingError):
    """
    P2P upload errors.
    """


class DHTConnectivityError(NetworkingError):
    """
    DHT connectivity issues.
    """


class DHTProtocolError(NetworkingError):
    """
    DHT protocol issues.
    """


class BlockchainError(BaseError):
    """
    **Blockchain**
    """


class TransactionRejectionError(BlockchainError):
    """
    Transaction rejected.
    """


class TransactionRejectedError(TransactionRejectionError):
    def __init__(self):
        super().__init__("Transaction rejected, unknown reason.")


class TransactionFeeTooLowError(TransactionRejectionError):
    def __init__(self):
        super().__init__("Fee too low.")


class TransactionInvalidSignatureError(TransactionRejectionError):
    def __init__(self):
        super().__init__("Invalid signature.")


class BalanceError(BlockchainError):
    """
    Errors related to your available balance.
    """


class InsufficientFundsError(BalanceError):
    """
    determined by wallet prior to attempting to broadcast a tx; this is different for example from a TX
    being created and sent but then rejected by lbrycrd for unspendable utxos.
    """
    def __init__(self):
        super().__init__("Insufficient funds.")


class ChannelSigningError(BlockchainError):
    """
    Channel signing.
    """


class ChannelKeyNotFoundError(ChannelSigningError):
    def __init__(self):
        super().__init__("Channel signing key not found.")


class ChannelKeyInvalidError(ChannelSigningError):
    """
    For example, channel was updated but you don't have the updated key.
    """
    def __init__(self):
        super().__init__("Channel signing key is out of date.")


class GeneralResolveError(BlockchainError):
    """
    Errors while resolving urls.
    """


class ResolveError(GeneralResolveError):
    def __init__(self, url):
        super().__init__(f"Failed to resolve '{url}'.")


class ResolveTimeoutError(GeneralResolveError):
    def __init__(self, url):
        super().__init__(f"Failed to resolve '{url}' within the timeout.")


class BlobError(BaseError):
    """
    **Blobs**
    """


class BlobAvailabilityError(BlobError):
    """
    Blob availability.
    """


class BlobNotFoundError(BlobAvailabilityError):
    def __init__(self):
        super().__init__("Blob not found.")


class BlobPermissionDeniedError(BlobAvailabilityError):
    def __init__(self):
        super().__init__("Permission denied to read blob.")


class BlobTooBigError(BlobAvailabilityError):
    def __init__(self):
        super().__init__("Blob is too big.")


class BlobEmptyError(BlobAvailabilityError):
    def __init__(self):
        super().__init__("Blob is empty.")


class BlobDecryptionError(BlobError):
    """
    Decryption / Assembly
    """


class BlobFailedDecryptionError(BlobDecryptionError):
    def __init__(self):
        super().__init__("Failed to decrypt blob.")


class CorruptBlobError(BlobDecryptionError):
    def __init__(self):
        super().__init__("Blobs is corrupted.")


class BlobEncryptionError(BlobError):
    """
    Encrypting / Creating
    """


class BlobFailedEncryptionError(BlobEncryptionError):
    def __init__(self):
        super().__init__("Failed to encrypt blob.")


class BlobRelatedError(BlobError):
    """
    Exceptions carried over from old error system.
    """


class DownloadCancelledError(BlobRelatedError):
    def __init__(self):
        super().__init__("Download was canceled.")


class DownloadSDTimeoutError(BlobRelatedError):
    def __init__(self, download):
        super().__init__(f"Failed to download sd blob {download} within timeout.")


class DownloadDataTimeoutError(BlobRelatedError):
    def __init__(self, download):
        super().__init__(f"Failed to download data blobs for sd hash {download} within timeout.")


class InvalidStreamDescriptorError(BlobRelatedError):
    def __init__(self, message):
        super().__init__(f"{message}")


class InvalidDataError(BlobRelatedError):
    def __init__(self, message):
        super().__init__(f"{message}")


class InvalidBlobHashError(BlobRelatedError):
    def __init__(self, message):
        super().__init__(f"{message}")


class ComponentError(BaseError):
    """
    **Components**
    """


class ComponentStartConditionNotMetError(ComponentError):
    def __init__(self, components):
        super().__init__(f"Unresolved dependencies for: {components}")


class ComponentsNotStartedError(ComponentError):
    def __init__(self, message):
        super().__init__(f"{message}")


class CurrencyExchangeError(BaseError):
    """
    **Currency Exchange**
    """


class InvalidExchangeRateResponseError(CurrencyExchangeError):
    def __init__(self, source, reason):
        super().__init__(f"Failed to get exchange rate from {source}: {reason}")


class CurrencyConversionError(CurrencyExchangeError):
    def __init__(self, message):
        super().__init__(f"{message}")


class InvalidCurrencyError(CurrencyExchangeError):
    def __init__(self, currency):
        super().__init__(f"Invalid currency: {currency} is not a supported currency.")


class PurchaseError(BaseError):
    """
    Purchase process errors.
    """


class KeyFeeAboveMaxAllowedError(PurchaseError):
    def __init__(self, message):
        super().__init__(f"{message}")

