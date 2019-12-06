from .base import BaseError


class UserInputError(BaseError):
    """
    User input errors.
    """


class CommandError(UserInputError):
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

    def __init__(self, argument, command):
        super().__init__(f"Invalid argument '{argument}' to command '{command}'.")


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


class InputValueError(UserInputError, ValueError):
    """
    Invalid argument value provided to command.
    """


class GenericInputValueError(InputValueError):

    def __init__(self, value, argument):
        super().__init__(f"The value '{value}' for argument '{argument}' is not valid.")


class ConfigurationError(BaseError):
    """
    Configuration errors.
    """


class ConfigWriteError(ConfigurationError):
    """
    When writing the default config fails on startup, such as due to permission issues.
    """

    def __init__(self, path):
        super().__init__(f"Cannot write configuration file '{path}'.")


class ConfigReadError(ConfigurationError):
    """
    Can't open the config file user provided via command line args.
    """

    def __init__(self, path):
        super().__init__(f"Cannot find provided configuration file '{path}'.")


class ConfigParseError(ConfigurationError):
    """
    Includes the syntax error / line number to help user fix it.
    """

    def __init__(self, path):
        super().__init__(f"Failed to parse the configuration file '{path}'.")


class ConfigMissingError(ConfigurationError):

    def __init__(self, path):
        super().__init__(f"Configuration file '{path}' is missing setting that has no default / fallback.")


class ConfigInvalidError(ConfigurationError):

    def __init__(self, path):
        super().__init__(f"Configuration file '{path}' has setting with invalid value.")


class NetworkError(BaseError):
    """
    **Networking**
    """


class NoInternetError(NetworkError):

    def __init__(self):
        super().__init__("No internet connection.")


class NoUPnPSupportError(NetworkError):

    def __init__(self):
        super().__init__("Router does not support UPnP.")


class WalletError(BaseError):
    """
    **Wallet Errors**
    """


class TransactionRejectedError(WalletError):

    def __init__(self):
        super().__init__("Transaction rejected, unknown reason.")


class TransactionFeeTooLowError(WalletError):

    def __init__(self):
        super().__init__("Fee too low.")


class TransactionInvalidSignatureError(WalletError):

    def __init__(self):
        super().__init__("Invalid signature.")


class InsufficientFundsError(WalletError):
    """
    determined by wallet prior to attempting to broadcast a tx; this is different for example from a TX
    being created and sent but then rejected by lbrycrd for unspendable utxos.
    """

    def __init__(self):
        super().__init__("Insufficient funds.")


class ChannelKeyNotFoundError(WalletError):

    def __init__(self):
        super().__init__("Channel signing key not found.")


class ChannelKeyInvalidError(WalletError):
    """
    For example, channel was updated but you don't have the updated key.
    """

    def __init__(self):
        super().__init__("Channel signing key is out of date.")


class DataDownloadError(WalletError):

    def __init__(self):
        super().__init__("Failed to download blob. *generic*")


class ResolveError(WalletError):

    def __init__(self, url):
        super().__init__(f"Failed to resolve '{url}'.")


class ResolveTimeoutError(WalletError):

    def __init__(self, url):
        super().__init__(f"Failed to resolve '{url}' within the timeout.")


class KeyFeeAboveMaxAllowedError(WalletError):

    def __init__(self, message):
        super().__init__(f"{message}")


class BlobError(BaseError):
    """
    **Blobs**
    """


class BlobNotFoundError(BlobError):

    def __init__(self):
        super().__init__("Blob not found.")


class BlobPermissionDeniedError(BlobError):

    def __init__(self):
        super().__init__("Permission denied to read blob.")


class BlobTooBigError(BlobError):

    def __init__(self):
        super().__init__("Blob is too big.")


class BlobEmptyError(BlobError):

    def __init__(self):
        super().__init__("Blob is empty.")


class BlobFailedDecryptionError(BlobError):

    def __init__(self):
        super().__init__("Failed to decrypt blob.")


class CorruptBlobError(BlobError):

    def __init__(self):
        super().__init__("Blobs is corrupted.")


class BlobFailedEncryptionError(BlobError):

    def __init__(self):
        super().__init__("Failed to encrypt blob.")


class DownloadCancelledError(BlobError):

    def __init__(self):
        super().__init__("Download was canceled.")


class DownloadSDTimeoutError(BlobError):

    def __init__(self, download):
        super().__init__(f"Failed to download sd blob {download} within timeout.")


class DownloadDataTimeoutError(BlobError):

    def __init__(self, download):
        super().__init__(f"Failed to download data blobs for sd hash {download} within timeout.")


class InvalidStreamDescriptorError(BlobError):

    def __init__(self, message):
        super().__init__(f"{message}")


class InvalidDataError(BlobError):

    def __init__(self, message):
        super().__init__(f"{message}")


class InvalidBlobHashError(BlobError):

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
