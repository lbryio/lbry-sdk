# LBRY Exceptions

Exceptions in LBRY are defined and generated from the Markdown table below.

Column | Meaning
---|---
Code | Codes are used only to define the hierarchy of exceptions and do not end up in the generated output, it is okay to re-number things as necessary to achieve the desired hierarchy.
Log | Log numbers map to the Python Logging Levels and specify at what log level a particular exception should be logged. For example, a Log of "4" would be ERROR log level.
Name | Generated class name for the error with "Error" appended to the end.
Message | User friendly error message explaining the error and possible solutions.

## Error Table

Code | Log | Name | Message
---:|---:|---|---
**1xx** |5| Initialization | **Daemon `start` and other CLI command failures (non-recoverable)**
**10x** |5| Client | Error codes reported by clients connecting to `lbrynet` daemon.
101 |5| RPCConnection | Failed to establish HTTP connection to `lbrynet`. (Is it running?)
102 |5| RPCUnresponsive | HTTP connection established but daemon is not responding to commands.
103 |5| WebSocketConnection | WebSocket connection established but daemon is not responding to commands.
104 |5| WebSocketUnresponsive | Failed to establish WebSocket connection to `lbrynet`. (Is it running?)
**11x** |5| Hardware | Enough of `lbrynet` was able to start to determine external factors causing eventual failure.
110 |5| OutOfSpace | Out of disk space.
111 |5| OutOfRAM | Out of RAM.
**12x** |5| Environment | Internal factors preventing `lbrynet` from bootstrapping itself.
120 |5| IncompatiblePython | Incompatible version of Python.
121 |5| IncompatibleDependency | Incompatible version of some library.
**13x** |5| Configuration | Configuration errors.
130 |5| CannotWriteConfiguration | Cannot write configuration file '{path}'. -- When writing the default config fails on startup, such as due to permission issues.
131 |5| CannotOpenConfiguration | Cannot find provided configuration file '{path}'. -- Can't open the config file user provided via command line args.
132 |5| CannotParseConfiguration | Failed to parse the configuration file '{path}'. -- Includes the syntax error / line number to help user fix it.
133 |5| ConfigurationMissing | Configuration file '{path}' is missing setting that has no default / fallback.
134 |5| ConfigurationInvalid | Configuration file '{path}' has setting with invalid value.
**14x** |5| Command | Errors preparing to execute commands.
140 |5| CommandDoesNotExist | Command '{command}' does not exist.
141 |5| CommandDeprecated | Command '{command}' is deprecated.
142 |5| CommandInvalidArgument | Invalid arguments for command '{command}'.
143 |5| CommandTemporarilyUnavailable | Command '{command}' is temporarily unavailable. -- Such as waiting for required components to start.
144 |5| CommandPermanentlyUnavailable | Command '{command}' is permanently unavailable. -- such as when required component was intentionally configured not to start.
**2xx** |5| Networking | **Networking**
**20x** |5| Connectivity | General connectivity.
201 |5| NoInternet | No internet connection.
202 |5| NoUPnPSupport | Router does not support UPnP.
**21x** |5| WalletConnectivity | Wallet server connectivity.
210 |5| WalletConnection | Failed connecting to a lbryumx server. -- Should normally not need to be handled higher up as `lbrynet` will retry other servers.
211 |5| WalletConnections | Failed connecting to all known lbryumx servers. -- Will need to bubble up and require user to do something.
212 |5| WalletConnectionDropped | lbryumx droppped our connection. -- Maybe we were being bad?
**22x** |5| WalletDisconnected | Wallet connection dropped.
220 |5| WalletServerSuspicious | Disconnected from lbryumx server due to suspicious responses. *generic*
221 |5| WalletServerValidation | Disconnected from lbryumx server due to SPV validation failure.
222 |5| WalletServerHeader | Disconnected from lbryumx server due to incorrect header received.
228 |5| WalletServerVersion | Disconnected from lbryumx server due to incompatible protocol version.
229 |5| WalletServerUnresponsive | Disconnected from lbryumx server due to unresponsiveness.
**23x** |5| DataConnectivity | P2P connection errors.
**24x** |5| DataNetwork | P2P download errors.
240 |5| DataDownload | Failed to download blob. *generic*
**25x** |5| DataUpload | P2P upload errors.
**26x** |5| DHTConnectivity | DHT connectivity issues.
**27x** |5| DHTProtocol | DHT protocol issues.
**3xx** |5| Blockchain | **Blockchain**
**30x** |5| TransactionRejection | Transaction rejected.
300 |5| TransactionRejected | Transaction rejected, unknown reason.
301 |5| TransactionFeeTooLow | Fee too low.
302 |5| TransactionInvalidSignature | Invalid signature.
**31x** |5| Balance | Errors related to your available balance.
311 |5| InsufficientFunds |  Insufficient funds. -- determined by wallet prior to attempting to broadcast a tx; this is different for example from a TX being created and sent but then rejected by lbrycrd for unspendable utxos.
**32x** |5| ChannelSigning | Channel signing.
320 |5| ChannelKeyNotFound | Channel signing key not found.
321 |5| ChannelKeyInvalid | Channel signing key is out of date. -- For example, channel was updated but you don't have the updated key.
**33x** |5| GeneralResolve | Errors while resolving urls.
331 |5| Resolve | Failed to resolve '{url}'.
332 |5| ResolveTimeout | Failed to resolve '{url}' within the timeout.
**4xx** |5| Blob | **Blobs**
**40x** |5| BlobAvailability | Blob availability.
400 |5| BlobNotFound | Blob not found.
401 |5| BlobPermissionDenied | Permission denied to read blob.
402 |5| BlobTooBig | Blob is too big.
403 |5| BlobEmpty | Blob is empty.
**41x** |5| BlobDecryption | Decryption / Assembly
410 |5| BlobFailedDecryption | Failed to decrypt blob.
411 |5| CorruptBlob | Blobs is corrupted.
**42x** |5| BlobEncryption | Encrypting / Creating
420 |5| BlobFailedEncryption | Failed to encrypt blob.
**43x** |5| BlobRelated | Exceptions carried over from old error system.
431 |5| DownloadCancelled | Download was canceled.
432 |5| DownloadSDTimeout | Failed to download sd blob {download} within timeout.
433 |5| DownloadDataTimeout | Failed to download data blobs for sd hash {download} within timeout.
434 |5| InvalidStreamDescriptor | {message}
435 |5| InvalidData | {message}
436 |5| InvalidBlobHash | {message}
**5xx** |5| Component | **Components**
501 |5| ComponentStartConditionNotMet | Unresolved dependencies for: {components}
502 |5| ComponentsNotStarted | {message}
**6xx** |5| CurrencyExchange | **Currency Exchange**
601 |5| InvalidExchangeRateResponse | Failed to get exchange rate from {source}: {reason}
602 |5| CurrencyConversion | {message}
603 |5| InvalidCurrency | Invalid currency: {currency} is not a supported currency.
**7xx** |5| Purchase | Purchase process errors.
701 |5| KeyFeeAboveMaxAllowed | {message}