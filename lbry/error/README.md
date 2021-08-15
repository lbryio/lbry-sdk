# Exceptions

Exceptions in LBRY are defined and generated from the Markdown table at the end of this README.

## Guidelines

When possible, use [built-in Python exceptions](https://docs.python.org/3/library/exceptions.html) or `aiohttp` [general client](https://docs.aiohttp.org/en/latest/client_reference.html#client-exceptions) / [HTTP](https://docs.aiohttp.org/en/latest/web_exceptions.html) exceptions, unless:
1. You want to provide a better error message (extend the closest built-in/`aiohttp` exception in this case).
2. You need to represent a new situation.

When defining your own exceptions, consider:
1. Extending a built-in Python or `aiohttp` exception.
2. Using contextual variables in the error message.

## Table Column Definitions

Column | Meaning
---|---
Code | Codes are used only to define the hierarchy of exceptions and do not end up in the generated output, it is okay to re-number things as necessary at anytime to achieve the desired hierarchy.
Name | Becomes the class name of the exception with "Error" appended to the end. Changing names of existing exceptions makes the API backwards incompatible. When extending other exceptions you must specify the full class name, manually adding "Error" as necessary (if extending another SDK exception).
Message | User friendly error message explaining the exceptional event. Supports Python formatted strings: any variables used in the string will be generated as arguments in the `__init__` method. Use `--` to provide a doc string after the error message to be added to the class definition.

## Exceptions Table

Code | Name | Message
---:|---|---
**1xx** | UserInput | User input errors.
**10x** | Command | Errors preparing to execute commands.
101 | CommandDoesNotExist | Command '{command}' does not exist.
102 | CommandDeprecated | Command '{command}' is deprecated.
103 | CommandInvalidArgument | Invalid argument '{argument}' to command '{command}'.
104 | CommandTemporarilyUnavailable | Command '{command}' is temporarily unavailable. -- Such as waiting for required components to start.
105 | CommandPermanentlyUnavailable | Command '{command}' is permanently unavailable. -- such as when required component was intentionally configured not to start.
**11x** | InputValue(ValueError) | Invalid argument value provided to command.
111 | GenericInputValue | The value '{value}' for argument '{argument}' is not valid.
112 | InputValueIsNone | None or null is not valid value for argument '{argument}'.
113 | ConflictingInputValue | Only '{first_argument}' or '{second_argument}' is allowed, not both.
114 | InputStringIsBlank | {argument} cannot be blank.
115 | EmptyPublishedFile | Cannot publish empty file: {file_path}
116 | MissingPublishedFile | File does not exist: {file_path}
117 | InvalidStreamURL | Invalid LBRY stream URL: '{url}' -- When an URL cannot be downloaded, such as '@Channel/' or a collection
**2xx** | Configuration | Configuration errors.
201 | ConfigWrite | Cannot write configuration file '{path}'. -- When writing the default config fails on startup, such as due to permission issues.
202 | ConfigRead | Cannot find provided configuration file '{path}'. -- Can't open the config file user provided via command line args.
203 | ConfigParse | Failed to parse the configuration file '{path}'. -- Includes the syntax error / line number to help user fix it.
204 | ConfigMissing | Configuration file '{path}' is missing setting that has no default / fallback.
205 | ConfigInvalid | Configuration file '{path}' has setting with invalid value.
**3xx** | Network | **Networking**
301 | NoInternet | No internet connection.
302 | NoUPnPSupport | Router does not support UPnP.
**4xx** | Wallet | **Wallet Errors**
401 | TransactionRejected | Transaction rejected, unknown reason.
402 | TransactionFeeTooLow | Fee too low.
403 | TransactionInvalidSignature | Invalid signature.
404 | InsufficientFunds |  Not enough funds to cover this transaction. -- determined by wallet prior to attempting to broadcast a tx; this is different for example from a TX being created and sent but then rejected by lbrycrd for unspendable utxos.
405 | ChannelKeyNotFound | Channel signing key not found.
406 | ChannelKeyInvalid | Channel signing key is out of date. -- For example, channel was updated but you don't have the updated key.
407 | DataDownload | Failed to download blob. *generic*
408 | PrivateKeyNotFound | Couldn't find private key for {key} '{value}'.
410 | Resolve | Failed to resolve '{url}'.
411 | ResolveTimeout | Failed to resolve '{url}' within the timeout.
411 | ResolveCensored | Resolve of '{url}' was censored by channel with claim id '{censor_id}'.
420 | KeyFeeAboveMaxAllowed | {message}
421 | InvalidPassword | Password is invalid.
422 | IncompatibleWalletServer | '{server}:{port}' has an incompatibly old version.
423 | TooManyClaimSearchParameters | {key} cant have more than {limit} items.
424 | AlreadyPurchased | You already have a purchase for claim_id '{claim_id_hex}'. Use --allow-duplicate-purchase flag to override.
431 | ServerPaymentInvalidAddress | Invalid address from wallet server: '{address}' - skipping payment round.
432 | ServerPaymentWalletLocked | Cannot spend funds with locked wallet, skipping payment round.
433 | ServerPaymentFeeAboveMaxAllowed | Daily server fee of {daily_fee} exceeds maximum configured of {max_fee} LBC.
434 | WalletNotLoaded | Wallet {wallet_id} is not loaded.
435 | WalletAlreadyLoaded | Wallet {wallet_path} is already loaded.
436 | WalletNotFound | Wallet not found at {wallet_path}.
437 | WalletAlreadyExists | Wallet {wallet_path} already exists, use `wallet_add` to load it.
**5xx** | Blob | **Blobs**
500 | BlobNotFound | Blob not found.
501 | BlobPermissionDenied | Permission denied to read blob.
502 | BlobTooBig | Blob is too big.
503 | BlobEmpty | Blob is empty.
510 | BlobFailedDecryption | Failed to decrypt blob.
511 | CorruptBlob | Blobs is corrupted.
520 | BlobFailedEncryption | Failed to encrypt blob.
531 | DownloadCancelled | Download was canceled.
532 | DownloadSDTimeout | Failed to download sd blob {download} within timeout.
533 | DownloadDataTimeout | Failed to download data blobs for sd hash {download} within timeout.
534 | InvalidStreamDescriptor | {message}
535 | InvalidData | {message}
536 | InvalidBlobHash | {message}
**6xx** | Component | **Components**
601 | ComponentStartConditionNotMet | Unresolved dependencies for: {components}
602 | ComponentsNotStarted | {message}
**7xx** | CurrencyExchange | **Currency Exchange**
701 | InvalidExchangeRateResponse | Failed to get exchange rate from {source}: {reason}
702 | CurrencyConversion | {message}
703 | InvalidCurrency | Invalid currency: {currency} is not a supported currency.
