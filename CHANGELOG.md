# Change Log
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/) with
regard to the json-rpc api.  As we're currently pre-1.0 release, we
can and probably will change functionality and break backwards compatability
at anytime.

## [Unreleased]
### Security
  *
  *

### Fixed
  * Fixed non-blocking call in `BlobFile._close_writer`
  *

### Deprecated
  *
  *

### Changed
  *
  *

### Added
  *
  *

### Removed
  *
  *


## [0.15.0] - 2017-08-15
### Fixed
 * Fixed reflector server blocking the `received_blob` reply on the server announcing the blob to the dht
 * Fixed incorrect formatting of "amount" fields
 * Fixed handling of SIGINT, SIGTERM.
 * Fixed shutdown sequence
 * Fix error when resolving an integer

### Deprecated
 * The API will no longer be served at the /lbryapi path. It will now be at the root.
 * Deprecated `send_amount_to_address` in favor of `wallet_send`

### Changed
 * Renamed `reflect` command to `file_reflect`
 * Allow IP addresses to be configured as reflector servers, not just host names.
 * Return list of blobs that were reflected from `file_reflect`

### Added
 * Added `wallet_send`, a command to send credits and tips
 * Added `reflector` keyword parameter to `file_reflect` command
 * Added configuration options for auto re-reflect
 * Added option to abandon by txid/nout


## [0.14.3] - 2017-08-04
### Fixed
 * Fixed incorrect formatting of "amount" fields

### Added
 * Added validation of currencies.
 * Added blob_announce API command

### Removed
 * Removed TempBlobManager
  * Removed old /view and /upload API paths
  *


## [0.14.2] - 2017-07-24
### Fixed
 * Fix for https://github.com/lbryio/lbry/issues/750
 * Fixed inconsistencies in claim_show output
 * Fixed daemon process hanging when started without an internet connection
 * Fixed https://github.com/lbryio/lbry/issues/774
 * Fix XDG compliance on Linux
 * Fixed https://github.com/lbryio/lbry/issues/760
 * Fixed default directories bug

### Changed
 * claim_show API command no longer takes name as argument
 * Linux default downloads folder changed from `~/Downloads` to `XDG_DOWNLOAD_DIR`
 * Linux folders moved from the home directory to `~/.local/share/lbry`
 * Windows folders moved from `%AppData%/Roaming` to `%AppData%/Local/lbry`
 * Changed `claim_list_by_channel` to return the `claims_in_channel` count instead of the `claims_in_channel_pages` count

### Added
 * Add link to instructions on how to change the default peer port
 * Add `peer_port` to settings configurable using `settings_set`
 * Added an option to disable max key fee check.


## [0.14.1] - 2017-07-07

### Fixed
 * Fixed timeout behaviour when calling API command get
 * Fixed https://github.com/lbryio/lbry/issues/765

### Removed
  * Removed stream_info_cache.json from daemon.py

## [0.14.0] - 2017-07-05

### Added
 * Missing docstring for `blob_list`
 * Added convenient import for setting up a daemon client, `from lbrynet.daemon import get_client`
 * Added unit tests for CryptBlob.py


### Changed
 * Change `max_key_fee` setting to be a dictionary with values for `currency` and `amount`
 * Renamed `lbrynet.lbryfile` to `lbrynet.lbry_file`
 * Renamed `lbrynet.lbryfilemanager` to `lbrynet.file_manager`
 * Renamed `lbrynet.lbrynet_daemon` to `lbrynet.daemon`
 * Initialize lbrynet settings when configuring an api client if they are not set yet
 * Updated lbryum imports
 * Improve error message when resolving a claim fails using the "get" command


### Removed
 * Removed unused settings from conf.py and `settings_set`
 * Removed download_directory argument from API command get


### Fixed
 * Fixed some log messages throwing exceptions
 * Fix shutdown of the blob tracker by Session
 * Fixed claim_new_support docstrings
 * Fixed BlobManager causing functional tests to fail, removed its unneeded manage() loop
 * Increased max_key_fee
 * Fixed unit tests on appveyor Windows build
 * Fixed [#692](https://github.com/lbryio/lbry/issues/692)



## [0.13.1] - 2017-06-15

### Added
 * Add `claim_send_to_address`
 * Add `change_address` argument to `publish`
 * Add `unique_contacts` count to `status` response


### Changed
 * Support resolution of multiple uris with `resolve`, all results are keyed by uri
 * Add `error` responses for failed resolves
 * Add `claim_list_by_channel`, supports multiple channel resolution
 * Rename delete_target_file argument of delete API command to delete_from_download_dir
 * Rename delete_all CLI flag -a to --delete_all


### Removed
 * Remove `claims_in_channel` from `resolve` response


### Fixed
 * Race condition from improper initialization and shutdown of the blob manager database
 * Various fixes for GetStream class used in API command get
 * Download analytics error
 * Fixed flag options in file_delete API command



## [0.11.0] - 2017-06-09

### Added
 * Added claim_address option to publish API command
 * Added message for InsufficientFundsError exception
 * Add CLI docs


### Changed
 * Do not catch base exception in API command resolve
 * Remove deprecated `lbrynet.metadata` and update what used it to instead use `lbryschema`
 * Get version information locally instead of via api for cli


### Deprecated
 * Old fee metadata format in publish API command is deprecated, throw relevant exception
 * Removed deprecated `get_best_blockhash`
 * Removed deprecated `is_running`
 * Removed deprecated `daemon_status`
 * Removed deprecated `is_first_run`
 * Removed deprecated `get_lbry_session_info`
 * Removed deprecated `get_time_behind_blockchain`
 * Removed deprecated `get_settings`
 * Removed deprecated `set_settings`
 * Removed deprecated `get_balance`
 * Removed deprecated `stop`
 * Removed deprecated `get_claim_info`
 * Removed deprecated `stop_lbry_file`
 * Removed deprecated `start_lbry_file`
 * Removed deprecated `get_est_cost`
 * Removed deprecated `abandon_claim`
 * Removed deprecated `support_claim`
 * Removed deprecated `get_my_claim`
 * Removed deprecated `get_name_claims`
 * Removed deprecated `get_claims_for_tx`
 * Removed deprecated `get_transaction_history`
 * Removed deprecated `get_transaction`
 * Removed deprecated `address_is_mine`
 * Removed deprecated `get_public_key_from_wallet`
 * Removed deprecated `get_new_address`
 * Removed deprecated `get_block`
 * Removed deprecated `descriptor_get`
 * Removed deprecated `download_descriptor`
 * Removed deprecated `get_peers_for_hash`
 * Removed deprecated `announce_all_blobs_to_dht`
 * Removed deprecated `get_blob_hashes`
 * Removed deprecated `reflect_all_blobs`
 * Removed deprecated `get_start_notice`


### Fixed
 * Download analytics error



## [0.10.3production4] - 2017-06-01

### Added
 * Prevent publish of files with size 0
 * Add `dht_status` parameter to `status` to include bandwidth and peer info
 * Positional and flag arguments in lbrynet-cli


### Changed
 * Changed keyword arguments in lbrynet-cli to use a -- prefix
 * Using the help function in lbrynet-cli no longer requires lbrynet-daemon to be running



## [0.10.3production3] - 2017-05-30

### Changed
 * Update `publish` to use {'currency': ..., 'address': ..., 'amount'} format for fee parameter, previously used old {currency: {'address': ..., 'amount': ...}} format


### Fixed
 * Allow claim_show to be used without specifying name
 * Fix licenseUrl field in `publish`



## [0.10.3production2] - 2017-05-30

### Fixed
 * Allow claim_show to be used without specifying name



## [0.10.3] - 2017-05-23

### Added
 * Add decorator to support queueing api calls
 * Added force option to API command resolve


### Changed
 * Added optional `address` and `include_unconfirmed` params to `jsonrpc_wallet_balance` method
 * Wait for subscriptions before announcing wallet has finished starting
 * Cache claims in wallet storage for use looking claims up by id or outpoint
 * Try to use cached claim info for `file_list`
 * Convert wallet storage to inlinecallbacks
 * Improve internal name_metadata sqlite table


### Fixed
 * Fix race condition in publish that resulted in claims being rejected when making many publishes concurrently



## [0.10.1] - 2017-05-03

### Fixed
 * Fix multiple reactor.stop() calls
 * Properly shut down lbryum wallet from lbrynet
 * Set LBRYumWallet.config upon initialization, fixes attribute error



## [0.10.0] - 2017-04-25

### Added
 * Add `lbryschema_version` to response from `version`
 * Added call to `get_address_balance` when `address` conditional returns true
 * Added `address` conditional to `jsonrpc_wallet_balance`
 * Added `get_address_balance` method to the `Wallet` class
### Changed
 * Added optional `address` and `include_unconfirmed` params to `jsonrpc_wallet_balance` method
 * Wait for subscriptions before announcing wallet has finished starting
### Fixed
 * fix stream_cost_estimate throwing exception on non decodeable claims
 * fixed signing of Windows binaries
 * fixed a few pylint warnings


## [0.10.0rc2] - 2017-04-17
### Changed
 * Return full `lbry_id` and `installation_id` from `status`


## [0.10.0rc1] - 2017-04-13
### Fixed
 * Fix uncaught exception in `stream_cost_estimate`


## [0.9.2rc22] - 2017-04-12
### Added
 * Add `claim_id` parameter to `claim_show`
 * Add `hex` field to claim responses for the raw claim value
 * Add an `error` field to to file responses if an error occurs
### Changed
 * Use `uri` instead of `name` in `get_availability`
 * Add `channel_name` to claim and file responses where applicable
 * Return None (instead of errors) if a uri cannot be resolved
 * Use `uri` instead of `name` for `stream_cost_estimate`, update cost estimate for lbryschema
### Fixed
 * `file_list` for files with bad signatures
 * return None from resolve commands when nothing is found
 * return lbry files with claims that are abandoned
 * unhelpful error messages in `publish` and `channel_new`

## [0.9.2rc9] - 2017-04-08
### Added
 * Use `claim_id` instead of outpoint for `claim_abandon`
 * Add `channel_name` parameter to `publish`
 * Add `delete_all` parameter to `file_delete` to allow deleting multiple files
 * Add `channel_list_mine`
 * Add `channel_new`
 * Add `resolve` to resolve lbry uris
### Changed
 * Use `uri` instead of `name` for `get`, remove explicit `claim_id` parameter
 * Increase default download timeout
 * Use lbry.io api for exchange rate data

## [0.9.2rc4] - 2017-04-06
### Changed
 * Use lbryschema library for metadata
### Fixed
 * Removed update_metadata function that could cause update problems
 * Fix DHT contact bug

## [0.9.2rc3] - 2017-03-29
### Added
 * Create wallet_unused_address API command
 * Add `claim_id` parameter to `get`, used to specify non-default claim for `name`
### Changed
 * wallet_new_address API command always returns new address
 * Improved ConnectionManager speed
 * Remove unused `stream_info` parameter in `get`

## [0.9.2rc2] - 2017-03-25
### Added
 * Add `wallet_list` command
 * Add checks for missing/extraneous params when calling jsonrpc commands
 * Added colors to cli error messages
### Changed
 * Removed check_pending logic from Daemon
 * Switched to txrequests so requests can use twisted event loop
 * Renamed API command file_seed to file_set_status
### Fixed
 * Fix restart procedure in DaemonControl
 * Create download directory if it doesn't exist
 * Fixed descriptor_get
 * Fixed jsonrpc_reflect()
 * Fixed api help return
 * Fixed API command descriptor_get
 * Fixed API command transaction_show
 * Fixed error handling for jsonrpc commands

## [0.9.2rc1] - 2017-03-21
### Added
 * Add `wallet_list` command
### Changed
 * Dont add expected payment to wallet when payment rate is 0
### Fixed
 * Fixed descriptor_get
 * Fixed jsonrpc_reflect()
 * Fixed api help return
 * Fixed API command descriptor_get
 * Fixed API command transaction_show
 * Handle failure to decode claim cache file

## [0.9.1] - 2017-03-17
### Fixed
 * Fix wallet_public_key API command

## [0.9.1rc5] - 2017-03-16
### Added
 * publish API command can take metadata fields as arguments
 * Added `reflect_uploads` config to disable reflecting on upload
### Fixed
 * Fixed jsonrpc_reflect()
 * Fixed api help return

## [0.9.1rc2] - 2017-03-15
### Added
 * Added `--version` flag
### Changed
 * Removed `simplejson` dependency in favor of bulitin `json`

## [0.9.0rc17] - 2017-03-10
### Fixed
 * Added string comparison to ClaimOutpoint (needed to look things up by outpoint)
 * Remove unused API commands from daemon
 * Fix file filter `outpoint`
 * Made dictionary key names in API commmand outputs to be more consistent

## [0.9.0rc15] - 2017-03-09
### Added
 * Add file filters: `claim_id`, `outpoint`, and `rowid`
 * Make loggly logs less verbose
### Changed
 * Change file filter `uri` to `name` and return field `lbry_uri` to `name`
 * Refactor file_list, add `full_status` argument to populate resource intensive fields
 * Remove deprecated file commands: `get_lbry_files`, `get_lbry_file`, and `file_get`
 * Remove deprecated `delete_lbry_file` command
 * Return standard file json from `get`
### Fixed
 * Added string comparison to ClaimOutpoint (needed to look things up by outpoint)
 * Remove unused API commands from daemon
 * Fix file filter `outpoint`

## [0.9.0rc12] - 2017-03-06
### Fixed
 * Fixed ExchangeRateManager freezing the app
 * Fixed download not timing out properly when downloading sd blob
  * Fixed ExchangeRateManager freezing the app
  * Fixed download not timing out properly when downloading sd blob
  * Fixed get not reassembling an already downloaded file that was deleted from download directory

## [0.9.0rc11] - 2017-02-27
### Fixed
 * Added timeout to ClientProtocol
 * Add check for when local height of wallet is less than zero

## [0.9.0rc9] - 2017-02-22
### Changed
 * Add blockchain status to jsonrpc_status

## [0.8.7] - 2017-02-21

## [0.8.6] - 2017-02-19

## [0.8.6rc0] - 2017-02-19
### Changed
 * Add `file_get` by stream hash
 * Add utils.call_later to replace reactor.callLater

### Fixed
 * Fix unhandled error in `get`
 * Fix sd blob timeout handling in `get_availability`, return 0.0

## [0.8.5] - 2017-02-18

## [0.8.5rc0] - 2017-02-18
### Fixed
 * Fix result expected by ui from file_get for missing files

## [0.8.4] - 2017-02-17

## [0.8.4rc0] - 2017-02-17
### Changed
 * Remove unused upload_allowed option
 * Remove code related to packaging as that step is now done in the electron client
 * Remove lbryum version check; use lbry-electron as version source
 * Include download url in version check

### Fixed
 * add misssing traceback to logging

## [0.8.3] - 2017-02-15
### Fixed
 * Get lbry files with pending claims
 * Add better logging to help track down [#478](https://github.com/lbryio/lbry/issues/478)
 * Catch UnknownNameErrors when resolving a name. [#479](https://github.com/lbryio/lbry/issues/479)

### Changed
 * Add blob_get, descriptor_get, and blob_delete
 * Add filter keyword args to blob_list
 * Refactor get_availability
 * Add optional peer search timeout, add peer_search_timeout setting

## [0.8.3rc3] - 2017-02-14

## [0.8.3rc2] - 2017-02-13

## [0.8.3rc1] - 2017-02-13
### Changed
 * make connection manager unit testeable

### Fixed
 * Change EWOULDBLOCK error in DHT to warning. #481
 * mark peers as down if it fails download protocol
 * Made hash reannounce time to be adjustable to fix [#432](https://github.com/lbryio/lbry/issues/432)


## [0.8.3rc0] - 2017-02-10
### Changed
 * Convert EncryptedFileDownloader to inlineCallbacks
 * Convert EncryptedFileManager to use inlineCallbacks
 * Convert Daemon._delete_lbry_file to inlineCallbacks
 * Add uri to stream reflector to de-obfuscate reflector logs
 * Simplify lbrynet.lbrynet_daemon.Publisher
 * Reflect streams in file manager looping call rather than in each file
 * Convert GetStream to inclineCallbacks
 * Change callback condition in GetStream to the first data blob completing
 * Add local and remote heights to blockchain status

### Fixed
 * Fix recursion depth error upon failed blob
 * Call stopProducing in reflector client file_sender when uploading is done
 * Ensure streams in stream_info_manager are saved in lbry_file_manager
 * Fixed file_delete not deleting data from stream_info_manager [#470](https://github.com/lbryio/lbry/issues/470)
 * Fixed upload of bug reports to Slack ([#472](https://github.com/lbryio/lbry/issues/472))
 * Fixed claim updates [#473](https://github.com/lbryio/lbry/issues/473)
 * Handle ConnectionLost error in reflector client
 * Fix updating a claim where the stream doesn't change
 * Fix claim_abandon

## [0.8.1] - 2017-02-01
### Changed
 * reflect all the blobs in a stream
 * change command line flags so that the more common usage is the default
 * change daemon function signatures to include names arguments

### Fixed
 * disable verbose twisted logs
 * improved wallet balance calculations
 * fix block too deep error

## [0.8.0] - 2017-01-24
### Changed
 * renamed api endpoints
 * improved command line user experience
 * integrate twisted logging with python logging
 * Updated READMEs

### Fixed
 * Fixed bug where ConnectionManager wasn't being stopped
 * Fixed: #343
 * Stop hanging if github is down
 * paths for debian package have been updated to be correct
 * improved output of the publish command
