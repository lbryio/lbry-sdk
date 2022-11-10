from .base import BaseError, claim_id


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
        self.command = command
        super().__init__(f"Command '{command}' does not exist.")


class CommandDeprecatedError(CommandError):

    def __init__(self, command):
        self.command = command
        super().__init__(f"Command '{command}' is deprecated.")


class CommandInvalidArgumentError(CommandError):

    def __init__(self, argument, command):
        self.argument = argument
        self.command = command
        super().__init__(f"Invalid argument '{argument}' to command '{command}'.")


class CommandTemporarilyUnavailableError(CommandError):
    """
    Such as waiting for required components to start.
    """

    def __init__(self, command):
        self.command = command
        super().__init__(f"Command '{command}' is temporarily unavailable.")


class CommandPermanentlyUnavailableError(CommandError):
    """
    such as when required component was intentionally configured not to start.
    """

    def __init__(self, command):
        self.command = command
        super().__init__(f"Command '{command}' is permanently unavailable.")


class InputValueError(UserInputError, ValueError):
    """
    Invalid argument value provided to command.
    """


class GenericInputValueError(InputValueError):

    def __init__(self, value, argument):
        self.value = value
        self.argument = argument
        super().__init__(f"The value '{value}' for argument '{argument}' is not valid.")


class InputValueIsNoneError(InputValueError):

    def __init__(self, argument):
        self.argument = argument
        super().__init__(f"None or null is not valid value for argument '{argument}'.")


class ConflictingInputValueError(InputValueError):

    def __init__(self, first_argument, second_argument):
        self.first_argument = first_argument
        self.second_argument = second_argument
        super().__init__(f"Only '{first_argument}' or '{second_argument}' is allowed, not both.")


class InputStringIsBlankError(InputValueError):

    def __init__(self, argument):
        self.argument = argument
        super().__init__(f"{argument} cannot be blank.")


class EmptyPublishedFileError(InputValueError):

    def __init__(self, file_path):
        self.file_path = file_path
        super().__init__(f"Cannot publish empty file: {file_path}")


class MissingPublishedFileError(InputValueError):

    def __init__(self, file_path):
        self.file_path = file_path
        super().__init__(f"File does not exist: {file_path}")


class InvalidStreamURLError(InputValueError):
    """
    When an URL cannot be downloaded, such as '@Channel/' or a collection
    """

    def __init__(self, url):
        self.url = url
        super().__init__(f"Invalid LBRY stream URL: '{url}'")


class ConfigurationError(BaseError):
    """
    Configuration errors.
    """


class ConfigWriteError(ConfigurationError):
    """
    When writing the default config fails on startup, such as due to permission issues.
    """

    def __init__(self, path):
        self.path = path
        super().__init__(f"Cannot write configuration file '{path}'.")


class ConfigReadError(ConfigurationError):
    """
    Can't open the config file user provided via command line args.
    """

    def __init__(self, path):
        self.path = path
        super().__init__(f"Cannot find provided configuration file '{path}'.")


class ConfigParseError(ConfigurationError):
    """
    Includes the syntax error / line number to help user fix it.
    """

    def __init__(self, path):
        self.path = path
        super().__init__(f"Failed to parse the configuration file '{path}'.")


class ConfigMissingError(ConfigurationError):

    def __init__(self, path):
        self.path = path
        super().__init__(f"Configuration file '{path}' is missing setting that has no default / fallback.")


class ConfigInvalidError(ConfigurationError):

    def __init__(self, path):
        self.path = path
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
        super().__init__("Not enough funds to cover this transaction.")


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


class PrivateKeyNotFoundError(WalletError):

    def __init__(self, key, value):
        self.key = key
        self.value = value
        super().__init__(f"Couldn't find private key for {key} '{value}'.")


class ResolveError(WalletError):

    def __init__(self, url):
        self.url = url
        super().__init__(f"Failed to resolve '{url}'.")


class ResolveTimeoutError(WalletError):

    def __init__(self, url):
        self.url = url
        super().__init__(f"Failed to resolve '{url}' within the timeout.")


class ResolveCensoredError(WalletError):

    def __init__(self, url, censor_id, censor_row):
        self.url = url
        self.censor_id = censor_id
        self.censor_row = censor_row
        super().__init__(f"Resolve of '{url}' was censored by channel with claim id '{censor_id}'.")


class KeyFeeAboveMaxAllowedError(WalletError):

    def __init__(self, message):
        self.message = message
        super().__init__(f"{message}")


class InvalidPasswordError(WalletError):

    def __init__(self):
        super().__init__("Password is invalid.")


class IncompatibleWalletServerError(WalletError):

    def __init__(self, server, port):
        self.server = server
        self.port = port
        super().__init__(f"'{server}:{port}' has an incompatibly old version.")


class TooManyClaimSearchParametersError(WalletError):

    def __init__(self, key, limit):
        self.key = key
        self.limit = limit
        super().__init__(f"{key} cant have more than {limit} items.")


class AlreadyPurchasedError(WalletError):
    """
    allow-duplicate-purchase flag to override.
    """

    def __init__(self, claim_id_hex):
        self.claim_id_hex = claim_id_hex
        super().__init__(f"You already have a purchase for claim_id '{claim_id_hex}'. Use")


class ServerPaymentInvalidAddressError(WalletError):

    def __init__(self, address):
        self.address = address
        super().__init__(f"Invalid address from wallet server: '{address}' - skipping payment round.")


class ServerPaymentWalletLockedError(WalletError):

    def __init__(self):
        super().__init__("Cannot spend funds with locked wallet, skipping payment round.")


class ServerPaymentFeeAboveMaxAllowedError(WalletError):

    def __init__(self, daily_fee, max_fee):
        self.daily_fee = daily_fee
        self.max_fee = max_fee
        super().__init__(f"Daily server fee of {daily_fee} exceeds maximum configured of {max_fee} LBC.")


class WalletNotLoadedError(WalletError):

    def __init__(self, wallet_id):
        self.wallet_id = wallet_id
        super().__init__(f"Wallet {wallet_id} is not loaded.")


class WalletAlreadyLoadedError(WalletError):

    def __init__(self, wallet_path):
        self.wallet_path = wallet_path
        super().__init__(f"Wallet {wallet_path} is already loaded.")


class WalletNotFoundError(WalletError):

    def __init__(self, wallet_path):
        self.wallet_path = wallet_path
        super().__init__(f"Wallet not found at {wallet_path}.")


class WalletAlreadyExistsError(WalletError):

    def __init__(self, wallet_path):
        self.wallet_path = wallet_path
        super().__init__(f"Wallet {wallet_path} already exists, use `wallet_add` to load it.")


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
        self.download = download
        super().__init__(f"Failed to download sd blob {download} within timeout.")


class DownloadDataTimeoutError(BlobError):

    def __init__(self, download):
        self.download = download
        super().__init__(f"Failed to download data blobs for sd hash {download} within timeout.")


class InvalidStreamDescriptorError(BlobError):

    def __init__(self, message):
        self.message = message
        super().__init__(f"{message}")


class InvalidDataError(BlobError):

    def __init__(self, message):
        self.message = message
        super().__init__(f"{message}")


class InvalidBlobHashError(BlobError):

    def __init__(self, message):
        self.message = message
        super().__init__(f"{message}")


class ComponentError(BaseError):
    """
    **Components**
    """


class ComponentStartConditionNotMetError(ComponentError):

    def __init__(self, components):
        self.components = components
        super().__init__(f"Unresolved dependencies for: {components}")


class ComponentsNotStartedError(ComponentError):

    def __init__(self, message):
        self.message = message
        super().__init__(f"{message}")


class CurrencyExchangeError(BaseError):
    """
    **Currency Exchange**
    """


class InvalidExchangeRateResponseError(CurrencyExchangeError):

    def __init__(self, source, reason):
        self.source = source
        self.reason = reason
        super().__init__(f"Failed to get exchange rate from {source}: {reason}")


class CurrencyConversionError(CurrencyExchangeError):

    def __init__(self, message):
        self.message = message
        super().__init__(f"{message}")


class InvalidCurrencyError(CurrencyExchangeError):

    def __init__(self, currency):
        self.currency = currency
        super().__init__(f"Invalid currency: {currency} is not a supported currency.")
