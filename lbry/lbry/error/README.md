Code | Name | Message | Comment
---:|---|---|---
**1xx** | Initialization | **Daemon `start` and other CLI command failures (non-recoverable)**
**10x** | Client | Error codes reported by clients connecting to `lbrynet` daemon.
101 | RPCConnection | Failed to establish HTTP connection to `lbrynet`. (Is it running?)
102 | RPCUnresponsive | HTTP connection established but daemon is not responding to commands.
103 | WebSocketConnection | WebSocket connection established but daemon is not responding to commands.
104 | WebSocketUnresponsive | Failed to establish WebSocket connection to `lbrynet`. (Is it running?)
**11x** | Hardware | Enough of `lbrynet` was able to start to determine external factors causing eventual failure.
110 | OutOfSpace | Out of disk space.
111 | OutOfRAM | Out of RAM.
**12x** | Environment | Internal factors preventing `lbrynet` from bootstrapping itself.
120 | IncompatiblePython | Incompatible version of Python.
121 | IncompatibleDependency | Incompatible version of some library.
**13x** | Configuration | Configuration errors.
130 | CannotWriteConfiguration | Cannot write configuration file '{path}'. | When writing the default config fails on startup, such as due to permission issues.
131 | CannotOpenConfiguration | Cannot find provided configuration file '{path}'. | Can't open the config file user provided via command line args.
132 | CannotParseConfiguration | Failed to parse the configuration file '{path}'. | Includes the syntax error / line number to help user fix it.
133 | ConfigurationMissing | Configuration file '{path}' is missing setting that has no default / fallback.
134 | ConfigurationInvalid | Configuration file '{path}' has setting with invalid value.
**14x** | Command | Errors preparing to execute commands.
140 | CommandDoesNotExist | Command '{command}' does not exist.
141 | CommandDeprecated | Command '{command}' is deprecated.
142 | CommandInvalidArgument | Invalid arguments for command '{command}'.
143 | CommandTemporarilyUnavailable | Command '{command}' is temporarily unavailable. | Such as waiting for required components to start.
144 | CommandPermanentlyUnavailable | Command '{command}' is permanently unavailable. | such as when required component was intentionally configured not to start.
**2xx** | Networking | **Networking**
**20x** | Connectivity | General connectivity.
201 | NoInternet | No internet connection.
202 | NoUPnPSupport | Router does not support UPnP.
**21x** | WalletConnectivity | Wallet server connectivity.
210 | WalletConnection | Failed connecting to a lbryumx server. | Should normally not need to be handled higher up as `lbrynet` will retry other servers.
211 | WalletConnections | Failed connecting to all known lbryumx servers. | Will need to bubble up and require user to do something.
212 | WalletConnectionDropped | lbryumx droppped our connection. | Maybe we were being bad?
**22x** | WalletDisconnected | Wallet connection dropped.
220 | WalletServerSuspicious | Disconnected from lbryumx server due to suspicious responses. *generic*
221 | WalletServerValidation | Disconnected from lbryumx server due to SPV validation failure.
222 | WalletServerHeader | Disconnected from lbryumx server due to incorrect header received.
228 | WalletServerVersion | Disconnected from lbryumx server due to incompatible protocol version.
229 | WalletServerUnresponsive | Disconnected from lbryumx server due to unresponsiveness.
**23x** | DataConnectivity | P2P connection errors.
**24x** | DataNetwork | P2P download errors.
240 | DataDownload | Failed to download blob. *generic*
**25x** | DataUpload | P2P upload errors.
**26x** | DHTConnectivity | DHT connectivity issues.
**27x** | DHTProtocol | DHT protocol issues.
**3xx** | Blockchain | **Blockchain**
**30x** | TransactionRejection | Transaction rejected.
300 | TransactionRejected | Transaction rejected, unknown reason.
301 | TransactionFeeTooLow | Fee too low.
302 | TransactionInvalidSignature | Invalid signature.
**31x** | InsufficientFunds | Insufficient funds. | determined by wallet prior to attempting to broadcast a tx; this is different for example from a TX being created and sent but then rejected by lbrycrd for unspendable utxos.
**32x** | ChannelSigning | Channel signing.
320 | ChannelKeyNotFound | Channel signing key not found.
321 | ChannelKeyInvalid | Channel signing key is out of date. | For example, channel was updated but you don't have the updated key.
**33x** | Resolve | Errors while resolving urls.
331 | ResolveError | Failed to resolve '{uri}'.
332 | ResolveTimeout | Failed to resolve '{uri}' within the timeout.
**4xx** | Blob | **Blobs**
**40x** | BlobAvailability | Blob availability.
400 | BlobNotFound | Blob not found.
401 | BlobPermissionDenied | Permission denied to read blob.
402 | BlobTooBig | Blob is too big.
403 | BlobEmpty | Blob is empty.
**41x** | BlobDecryption | Decryption / Assembly
410 | BlobFailedDecryption | Failed to decrypt blob.
411 | CorruptBlob | Blobs is corrupted.
**42x** | BlobEncryption | Encrypting / Creating
420 | BlobFailedEncryption | Failed to encrypt blob.
**43x** | BlobRelated | Exceptions carried over from old error system.
431 | DownloadCancelled | Download was canceled.
432 | DownloadSDTimeout | Failed to download sd blob {download} within timeout.
433 | DownloadDataTimeout | Failed to download data blobs for sd hash {download} within timeout.
434 | InvalidStreamDescriptor | {message}
435 | InvalidData | {message}
436 | InvalidBlobHash | {message}
**5xx** | Component | **Components**
501 | ComponentStartConditionNotMet | Unresolved dependencies for: {components}
502 | ComponentsNotStarted | {message}
**6xx** | CurrencyExchange | **Currency Exchange**
601 | InvalidExchangeRateResponse | Failed to get exchange rate from {source}: {reason}
602 | CurrencyConversion | {message}
603 | InvalidCurrency | Invalid currency: {currency} is not a supported currency.
**7xx** | Purchase | Purchase process errors.
701 | KeyFeeAboveMaxAllowed | {message}