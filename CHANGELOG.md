# Change Log
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/) with
regard to the json-rpc api.  As we're currently pre-1.0 release, we
can and probably will change functionality and break backwards compatability
at anytime.

## [Unreleased]
### Added
  * Add `wallet_list` command
  *
  *

### Changed
  * Dont add expected payment to wallet when payment rate is 0
  *
  *

### Fixed
  *
  *
  *

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
  * 

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
