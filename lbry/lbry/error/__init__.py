from .base import BaseError


class InitializationError(BaseError):
    """
    **Daemon `start` and other CLI command failures (non-recoverable)**
    """
    log_level = 50


class ClientError(InitializationError):
    """
    Error codes reported by clients connecting to `lbrynet` daemon.
    """
    log_level = 50


class RPCConnectionError(ClientError):
    log_level = 50
    def __init__(self):
        super().__init__("Failed to establish HTTP connection to `lbrynet`. (Is it running?)")


class RPCUnresponsiveError(ClientError):
    log_level = 50
    def __init__(self):
        super().__init__("HTTP connection established but daemon is not responding to commands.")


class WebSocketConnectionError(ClientError):
    log_level = 50
    def __init__(self):
        super().__init__("WebSocket connection established but daemon is not responding to commands.")


class WebSocketUnresponsiveError(ClientError):
    log_level = 50
    def __init__(self):
        super().__init__("Failed to establish WebSocket connection to `lbrynet`. (Is it running?)")


class HardwareError(InitializationError):
    """
    Enough of `lbrynet` was able to start to determine external factors causing eventual failure.
    """
    log_level = 50


class OutOfSpaceError(HardwareError):
    log_level = 50
    def __init__(self):
        super().__init__("Out of disk space.")


class OutOfRAMError(HardwareError):
    log_level = 50
    def __init__(self):
        super().__init__("Out of RAM.")


class EnvironmentError(InitializationError):
    """
    Internal factors preventing `lbrynet` from bootstrapping itself.
    """
    log_level = 50


class IncompatiblePythonError(EnvironmentError):
    log_level = 50
    def __init__(self):
        super().__init__("Incompatible version of Python.")


class IncompatibleDependencyError(EnvironmentError):
    log_level = 50
    def __init__(self):
        super().__init__("Incompatible version of some library.")


class ConfigurationError(InitializationError):
    """
    Configuration errors.
    """
    log_level = 50


class CannotWriteConfigurationError(ConfigurationError):
    """
    When writing the default config fails on startup, such as due to permission issues.
    """
    log_level = 50
    def __init__(self, path):
        super().__init__(f"Cannot write configuration file '{path}'.")


class CannotOpenConfigurationError(ConfigurationError):
    """
    Can't open the config file user provided via command line args.
    """
    log_level = 50
    def __init__(self, path):
        super().__init__(f"Cannot find provided configuration file '{path}'.")


class CannotParseConfigurationError(ConfigurationError):
    """
    Includes the syntax error / line number to help user fix it.
    """
    log_level = 50
    def __init__(self, path):
        super().__init__(f"Failed to parse the configuration file '{path}'.")


class ConfigurationMissingError(ConfigurationError):
    log_level = 50
    def __init__(self, path):
        super().__init__(f"Configuration file '{path}' is missing setting that has no default / fallback.")


class ConfigurationInvalidError(ConfigurationError):
    log_level = 50
    def __init__(self, path):
        super().__init__(f"Configuration file '{path}' has setting with invalid value.")


class CommandError(InitializationError):
    """
    Errors preparing to execute commands.
    """
    log_level = 50


class CommandDoesNotExistError(CommandError):
    log_level = 50
    def __init__(self, command):
        super().__init__(f"Command '{command}' does not exist.")


class CommandDeprecatedError(CommandError):
    log_level = 50
    def __init__(self, command):
        super().__init__(f"Command '{command}' is deprecated.")


class CommandInvalidArgumentError(CommandError):
    log_level = 50
    def __init__(self, command):
        super().__init__(f"Invalid arguments for command '{command}'.")


class CommandTemporarilyUnavailableError(CommandError):
    """
    Such as waiting for required components to start.
    """
    log_level = 50
    def __init__(self, command):
        super().__init__(f"Command '{command}' is temporarily unavailable.")


class CommandPermanentlyUnavailableError(CommandError):
    """
    such as when required component was intentionally configured not to start.
    """
    log_level = 50
    def __init__(self, command):
        super().__init__(f"Command '{command}' is permanently unavailable.")


class NetworkingError(BaseError):
    """
    **Networking**
    """
    log_level = 50


class ConnectivityError(NetworkingError):
    """
    General connectivity.
    """
    log_level = 50


class NoInternetError(ConnectivityError):
    log_level = 50
    def __init__(self):
        super().__init__("No internet connection.")


class NoUPnPSupportError(ConnectivityError):
    log_level = 50
    def __init__(self):
        super().__init__("Router does not support UPnP.")


class WalletConnectivityError(NetworkingError):
    """
    Wallet server connectivity.
    """
    log_level = 50


class WalletConnectionError(WalletConnectivityError):
    """
    Should normally not need to be handled higher up as `lbrynet` will retry other servers.
    """
    log_level = 50
    def __init__(self):
        super().__init__("Failed connecting to a lbryumx server.")


class WalletConnectionsError(WalletConnectivityError):
    """
    Will need to bubble up and require user to do something.
    """
    log_level = 50
    def __init__(self):
        super().__init__("Failed connecting to all known lbryumx servers.")


class WalletConnectionDroppedError(WalletConnectivityError):
    """
    Maybe we were being bad?
    """
    log_level = 50
    def __init__(self):
        super().__init__("lbryumx droppped our connection.")


class WalletDisconnectedError(NetworkingError):
    """
    Wallet connection dropped.
    """
    log_level = 50


class WalletServerSuspiciousError(WalletDisconnectedError):
    log_level = 50
    def __init__(self):
        super().__init__("Disconnected from lbryumx server due to suspicious responses. *generic*")


class WalletServerValidationError(WalletDisconnectedError):
    log_level = 50
    def __init__(self):
        super().__init__("Disconnected from lbryumx server due to SPV validation failure.")


class WalletServerHeaderError(WalletDisconnectedError):
    log_level = 50
    def __init__(self):
        super().__init__("Disconnected from lbryumx server due to incorrect header received.")


class WalletServerVersionError(WalletDisconnectedError):
    log_level = 50
    def __init__(self):
        super().__init__("Disconnected from lbryumx server due to incompatible protocol version.")


class WalletServerUnresponsiveError(WalletDisconnectedError):
    log_level = 50
    def __init__(self):
        super().__init__("Disconnected from lbryumx server due to unresponsiveness.")


class DataConnectivityError(NetworkingError):
    """
    P2P connection errors.
    """
    log_level = 50


class DataNetworkError(NetworkingError):
    """
    P2P download errors.
    """
    log_level = 50


class DataDownloadError(DataNetworkError):
    log_level = 50
    def __init__(self):
        super().__init__("Failed to download blob. *generic*")


class DataUploadError(NetworkingError):
    """
    P2P upload errors.
    """
    log_level = 50


class DHTConnectivityError(NetworkingError):
    """
    DHT connectivity issues.
    """
    log_level = 50


class DHTProtocolError(NetworkingError):
    """
    DHT protocol issues.
    """
    log_level = 50


class BlockchainError(BaseError):
    """
    **Blockchain**
    """
    log_level = 50


class TransactionRejectionError(BlockchainError):
    """
    Transaction rejected.
    """
    log_level = 50


class TransactionRejectedError(TransactionRejectionError):
    log_level = 50
    def __init__(self):
        super().__init__("Transaction rejected, unknown reason.")


class TransactionFeeTooLowError(TransactionRejectionError):
    log_level = 50
    def __init__(self):
        super().__init__("Fee too low.")


class TransactionInvalidSignatureError(TransactionRejectionError):
    log_level = 50
    def __init__(self):
        super().__init__("Invalid signature.")


class BalanceError(BlockchainError):
    """
    Errors related to your available balance.
    """
    log_level = 50


class InsufficientFundsError(BalanceError):
    """
    determined by wallet prior to attempting to broadcast a tx; this is different for example from a TX
    being created and sent but then rejected by lbrycrd for unspendable utxos.
    """
    log_level = 50
    def __init__(self):
        super().__init__("Insufficient funds.")


class ChannelSigningError(BlockchainError):
    """
    Channel signing.
    """
    log_level = 50


class ChannelKeyNotFoundError(ChannelSigningError):
    log_level = 50
    def __init__(self):
        super().__init__("Channel signing key not found.")


class ChannelKeyInvalidError(ChannelSigningError):
    """
    For example, channel was updated but you don't have the updated key.
    """
    log_level = 50
    def __init__(self):
        super().__init__("Channel signing key is out of date.")


class GeneralResolveError(BlockchainError):
    """
    Errors while resolving urls.
    """
    log_level = 50


class ResolveError(GeneralResolveError):
    log_level = 50
    def __init__(self, url):
        super().__init__(f"Failed to resolve '{url}'.")


class ResolveTimeoutError(GeneralResolveError):
    log_level = 50
    def __init__(self, url):
        super().__init__(f"Failed to resolve '{url}' within the timeout.")


class BlobError(BaseError):
    """
    **Blobs**
    """
    log_level = 50


class BlobAvailabilityError(BlobError):
    """
    Blob availability.
    """
    log_level = 50


class BlobNotFoundError(BlobAvailabilityError):
    log_level = 50
    def __init__(self):
        super().__init__("Blob not found.")


class BlobPermissionDeniedError(BlobAvailabilityError):
    log_level = 50
    def __init__(self):
        super().__init__("Permission denied to read blob.")


class BlobTooBigError(BlobAvailabilityError):
    log_level = 50
    def __init__(self):
        super().__init__("Blob is too big.")


class BlobEmptyError(BlobAvailabilityError):
    log_level = 50
    def __init__(self):
        super().__init__("Blob is empty.")


class BlobDecryptionError(BlobError):
    """
    Decryption / Assembly
    """
    log_level = 50


class BlobFailedDecryptionError(BlobDecryptionError):
    log_level = 50
    def __init__(self):
        super().__init__("Failed to decrypt blob.")


class CorruptBlobError(BlobDecryptionError):
    log_level = 50
    def __init__(self):
        super().__init__("Blobs is corrupted.")


class BlobEncryptionError(BlobError):
    """
    Encrypting / Creating
    """
    log_level = 50


class BlobFailedEncryptionError(BlobEncryptionError):
    log_level = 50
    def __init__(self):
        super().__init__("Failed to encrypt blob.")


class BlobRelatedError(BlobError):
    """
    Exceptions carried over from old error system.
    """
    log_level = 50


class DownloadCancelledError(BlobRelatedError):
    log_level = 50
    def __init__(self):
        super().__init__("Download was canceled.")


class DownloadSDTimeoutError(BlobRelatedError):
    log_level = 50
    def __init__(self, download):
        super().__init__(f"Failed to download sd blob {download} within timeout.")


class DownloadDataTimeoutError(BlobRelatedError):
    log_level = 50
    def __init__(self, download):
        super().__init__(f"Failed to download data blobs for sd hash {download} within timeout.")


class InvalidStreamDescriptorError(BlobRelatedError):
    log_level = 50
    def __init__(self, message):
        super().__init__(f"{message}")


class InvalidDataError(BlobRelatedError):
    log_level = 50
    def __init__(self, message):
        super().__init__(f"{message}")


class InvalidBlobHashError(BlobRelatedError):
    log_level = 50
    def __init__(self, message):
        super().__init__(f"{message}")


class ComponentError(BaseError):
    """
    **Components**
    """
    log_level = 50


class ComponentStartConditionNotMetError(ComponentError):
    log_level = 50
    def __init__(self, components):
        super().__init__(f"Unresolved dependencies for: {components}")


class ComponentsNotStartedError(ComponentError):
    log_level = 50
    def __init__(self, message):
        super().__init__(f"{message}")


class CurrencyExchangeError(BaseError):
    """
    **Currency Exchange**
    """
    log_level = 50


class InvalidExchangeRateResponseError(CurrencyExchangeError):
    log_level = 50
    def __init__(self, source, reason):
        super().__init__(f"Failed to get exchange rate from {source}: {reason}")


class CurrencyConversionError(CurrencyExchangeError):
    log_level = 50
    def __init__(self, message):
        super().__init__(f"{message}")


class InvalidCurrencyError(CurrencyExchangeError):
    log_level = 50
    def __init__(self, currency):
        super().__init__(f"Invalid currency: {currency} is not a supported currency.")


class PurchaseError(BaseError):
    """
    Purchase process errors.
    """
    log_level = 50


class KeyFeeAboveMaxAllowedError(PurchaseError):
    log_level = 50
    def __init__(self, message):
        super().__init__(f"{message}")

