# Change Log
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/) with
regard to the json-rpc api.  As we're currently pre-1.0 release, we
can and probably will change functionality and break backwards compatibility
at anytime.

## [Unreleased]
Python 3 upgrade of the entire code base and switching to a brand new wallet
implementation are the major changes in this release.

### Security
  * upgraded `cryptography` package.

### API
  * unified all command line executables into a single `lbrynet` executable.
  * deprecated `daemon_stop` command, use `stop` instead.
  * deprecated `wallet_balance` command, use `account_balance` instead.
  * deprecated `wallet_unlock` command, use `account_unlock` instead.
  * deprecated `wallet_decrypt` command, use `account_decrypt` instead.
  * deprecated `wallet_encrypt` command, use `account_encrypt` instead.
  * deprecated `wallet_prefill_addresses` command, use `account_fund` instead.
  * deprecated `wallet_list` command, use `address_list` instead.
  * deprecated `wallet_is_address_mine` command, use `address_is_mine` instead.
  * deprecated `wallet_public_key` command, use `address_public_key` instead.
  * deprecated `wallet_new_address` command, use `address_generate` instead.
  * deprecated `wallet_unused_address` command, use `address_unused` instead.
  * added `account_list` command to list accounts including their balance.
  * added `account_add` command to add a previously created account from seed or private key.
  * added `account_create` command to generate a new account.
  * added `account_remove` command to remove an account from wallet.
  * added `account_set` command to change a setting on an account.
  * added `account_balance` command to get just the account balance.
  * added `account_unlock` command to unlock an account.
  * added `account_encrypt` command to encrypt an account.
  * added `account_decrypt` command to decrypt an account.
  * added `account_fund` command to move funds between or within an account in various ways.
  * added `account_max_address_gap` command to find large gaps of unused addresses.
  * added `address_list` command to list addresses.
  * added `address_is_mine` command to check if an address is one of your addresses.
  * added `address_public_key` command to get public key of an address.
  * added `address_generate` command to generate a new address.
  * added `address_unused` command to get existing or generate a new unused address.
  * removed `send_amount_to_address` command previously marked as deprecated
  * removed `channel_list_mine` command previously marked as deprecated
  * removed `get_availability` command previously marked as deprecated

### Wallet
  * changed to a new wallet implementation: torba.
  * changed wallet file format to support multiple accounts in one wallet.
  * moved transaction data from wallet file into an sqlite database.
  * changed channel certificates to be keyed by txid:nout instead of claim_id which
    makes it possible to recover old certificates.

### DHT
  * Extensive internal changes as a result of porting to Python 3.

### P2P & File Manager
  * Extensive internal changes as a result of porting to Python 3.

### Database
  * 

### Reflector
  *

## [0.21.2] - 2018-08-23
### Fixed
 * issue in dht ping queue where enqueued pings that aren't yet due wouldn't be rescheduled
 * blob mirror downloader not finishing streams that were partially uploaded at the time of the download attempt (https://github.com/lbryio/lbry/issues/1376)


## [0.21.1] - 2018-08-13
### Fixed
 * `download_progress` field in `blockchain_headers` section of `status` not initializing correctly when resuming a download (https://github.com/lbryio/lbry/issues/1355)
 * `wallet_send` not accepting decimal amounts (https://github.com/lbryio/lbry/issues/1356 commit https://github.com/lbryio/lbry/commit/1098ca0494ece420c70fc57f69d6d388715a99b8)

### Added
 * `is_locked` to `wallet` in `status` response (https://github.com/lbryio/lbry/issues/1354, commit https://github.com/lbryio/lbry/commit/153022a1a7122ab6d31d3db433dccbe469bbcb3c)

### Changed
 * Bumped `lbryum` requirement to 3.2.4 [see changelog](https://github.com/lbryio/lbryum/blob/master/CHANGELOG.md#324---2018-08-13)

## [0.21.0] - 2018-08-09
### Fixed
 * check `claim_address` and `change_address` earlier on publishing, to avoid hard to understand errors later in the process (pr https://github.com/lbryio/lbry/pull/1347)
 * loggly error reporting not following `share_usage_data` (pr https://github.com/lbryio/lbry/pull/1328)
 * improper error handling when data is not valid JSON (pr https://github.com/lbryio/lbry/pull/1326)
 * blob mirroring being set in unrelated tests, making them fail (pr https://github.com/lbryio/lbry/pull/1348)
 * http blob mirroring edge cases (pr https://github.com/lbryio/lbry/pull/1315)
 * external ports in log messages not showing the correct external port from the upnp redirects (https://github.com/lbryio/lbry/issues/1338) (pr https://github.com/lbryio/lbry/pull/1349)
 * miniupnpc fallback issues in txupnp (https://github.com/lbryio/lbry/issues/1341) (pr https://github.com/lbryio/lbry/pull/1349)
 * upnp error when disabled on router and a non-gateway is found, such as chromecast (https://github.com/lbryio/lbry/issues/1352) (https://github.com/lbryio/lbry/commit/dca4af942fbe95547794213775f0a62cd04a393f)

### Deprecated
 * automatic claim renew, this is no longer needed

### Changed
 * api server class to use components, and for all JSONRPC API commands to be callable so long as the required components are available. (pr https://github.com/lbryio/lbry/pull/1294)
 * return error messages when required conditions on components are not met for API calls (pr https://github.com/lbryio/lbry/pull/1328)
 * `status` to no longer return a base58 encoded `lbry_id`, instead return this as the hex encoded `node_id` in a new `dht` field. (pr https://github.com/lbryio/lbry/pull/1328)
 * `startup_status` field in the response to `status` to be a dict of component names to status booleans (pr https://github.com/lbryio/lbry/pull/1328)
 * renamed the `blockchain_status` field in the response to `status` to `wallet` (pr https://github.com/lbryio/lbry/pull/1328)
 * moved and renamed `wallet_is_encrypted` to `is_encrypted` in the `wallet` field in the response to `status` (pr https://github.com/lbryio/lbry/pull/1328)
 * moved wallet, upnp and dht startup code from `Session` to `Components` (pr https://github.com/lbryio/lbry/pull/1328)
 * attempt blob downloads from http mirror sources (by default) concurrently to p2p sources (pr https://github.com/lbryio/lbry/pull/1233)
 * replace miniupnpc with [txupnp](https://github.com/lbryio/txupnp). Since txupnp is still under development, it will internally fall back to miniupnpc. (pr https://github.com/lbryio/lbry/pull/1328)
 * simplified test_misc.py in the functional tests (pr https://github.com/lbryio/lbry/pull/1328)
 * update `cryptography` requirement to 2.3 (pr https://github.com/lbryio/lbry/pull/1333)

### Added
 * `skipped_components` list to the response from `status` (pr https://github.com/lbryio/lbry/pull/1328)
 * component statuses (`blockchain_headers`, `dht`, `wallet`, `blob_manager` `hash_announcer`, and `file_manager`) to the response to `status` (pr https://github.com/lbryio/lbry/pull/1328)
 * `skipped_components` config setting, accepts a list of names of components to not run (pr https://github.com/lbryio/lbry/pull/1294)
 * `ComponentManager` for managing the life-cycles of dependencies (pr https://github.com/lbryio/lbry/pull/1294)
 * `requires` decorator to register the components required by a `jsonrpc_` command, to facilitate commands registering asynchronously (pr https://github.com/lbryio/lbry/pull/1294)
 * unit tests for `ComponentManager` (pr https://github.com/lbryio/lbry/pull/1294)
 * script to generate docs/api.json file (https://github.com/lbryio/lbry.tech/issues/42)
 * additional information to the balance error message when editing a claim (pr https://github.com/lbryio/lbry/pull/1309)
 * `address` and `port` arguments to `peer_ping` (https://github.com/lbryio/lbry/issues/1313) (pr https://github.com/lbryio/lbry/pull/1299)
 * ability to download from HTTP mirrors by setting `download_mirrors` (prs https://github.com/lbryio/lbry/pull/1233 and https://github.com/lbryio/lbry/pull/1315)
 * ability to filter peers from an iterative find value operation (finding peers for a blob). This is used to filter peers we've already found for a blob when accumulating the list of peers. (pr https://github.com/lbryio/lbry/pull/1287)

### Removed
 * `session_status` argument and response field from `status` (pr https://github.com/lbryio/lbry/pull/1328)
 * most of the internal attributes from `Daemon` (pr https://github.com/lbryio/lbry/pull/1294)


## [0.20.4] - 2018-07-18
### Fixed
 * spelling errors in messages printed by `lbrynet-cli`
 * high CPU usage when a stream is incomplete and the peers we're requesting from have no more blobs to send us (https://github.com/lbryio/lbry/pull/1301)

### Changed
 * keep track of failures for DHT peers for up to ten minutes instead of indefinitely (https://github.com/lbryio/lbry/pull/1300)
 * skip ignored peers from iterative lookups instead of blocking the peer who returned them to us too (https://github.com/lbryio/lbry/pull/1300)
 * if a node becomes ignored during an iterative find cycle remove it from the shortlist so that we can't return it as a result nor try to probe it anyway (https://github.com/lbryio/lbry/pull/1303)


## [0.20.3] - 2018-07-03
### Fixed
 * `blob_list` raising an error when blobs in a stream haven't yet been created (8a0d0b44ddf9cbeb2a9074eed39d6064ce21df64)
 * stopping a download potentially raising an attribute error (https://github.com/lbryio/lbry/pull/1269)
 * file manager startup locking up when there are many files for some channels (https://github.com/lbryio/lbry/pull/1281)
 * improper sorting when getting the closest peers to a hash (https://github.com/lbryio/lbry/pull/1282)

### Changed
 * raised the default `peer_search_timeout` setting from 3 to 30 and added logging for when it happens (https://github.com/lbryio/lbry/pull/1283)
 * change iterative find stop condition on find value to allow it to continue until a value is found or it times out (https://github.com/lbryio/lbry/pull/1283)
 * include all of our own blobs in the local dht datastore (as if we had announced them to ourselves) (https://github.com/lbryio/lbry/pull/1280)
 * ignore dht `store` token validation errors for the first expiration-time after startup (fixes failed `store` requests after a restart) (https://github.com/lbryio/lbry/pull/1280)

### Removed
 * `jsonrpclib` as a requirement for the project (https://github.com/lbryio/lbry/pull/1274)


## [0.20.2] - 2018-06-23
### Changed
 * Bumped `lbryschema` requirement to 0.0.16 [see changelog](https://github.com/lbryio/lbryschema/blob/master/CHANGELOG.md#0016---2018-06-23)
 * Bumped `lbryum` requirement to 3.2.3 [see changelog](https://github.com/lbryio/lbryum/blob/master/CHANGELOG.md#323---2018-06-23)
 * save claims to sqlite in batches to speed up `resolve` queries for many uris


## [0.20.1] - 2018-06-19
### Fixed
 * fixed token validation error when the dht node has just been started (https://github.com/lbryio/lbry/issues/1248)
 * fixed a race condition when inserting a blob into the database (https://github.com/lbryio/lbry/issues/1129)
 * reflector server incorrectly responding as if it has all the blobs for a stream that was only partially uploaded to it
 * `publish` raising a database error when updating a claim that we don't have a file for (https://github.com/lbryio/lbry/issues/1165)
 * blob client protocol not tearing itself down properly after a failure (https://github.com/lbryio/lbry/issues/950)
 * lockup in wallet startup when one or more lbryumx servers are unavailable (https://github.com/lbryio/lbry/issues/1245)
 * download being stopped if the sd blob downloaded and data did not start within the timeout (https://github.com/lbryio/lbry/issues/1172)

### Changed
 * Bumped `lbryum` requirement to 3.2.2 [see changelog](https://github.com/lbryio/lbryum/blob/master/CHANGELOG.md#322---2018-06-19)
 * `publish` to accept bid as a decimal string


## [0.20.0] - 2018-06-13

### TL;DR
  This milestone release includes a large number of bug fixes, changes and additions covering all aspects of the daemon. Notable improvements include:

  * Faster and more reliable downloading and uploading of content resulting from substantial work done on the Distributed Hash Table algorithms and protocol.
  * Faster blockchain synchronization (headers) by downloading them from Amazon S3 under certain conditions.
  * Faster overall app startup due to better optimized SQL queries.
  * Power users of the `lbrynet-cli` will benefit from many bug fixes to commonly used commands and improvements in sorting of output.
  * Please review the full change log for more details on specific fixes, changes and additions.

### Fixed
 * fix payment rate manager typo ([1236](https://github.com/lbryio/lbry/pull/1236))
 * handling error from dht clients with old `ping` method
 * blobs not being re-announced if no peers successfully stored, now failed announcements are re-queued
 * issue where an `AuthAPIClient` (used by `lbrynet-cli`) would fail to update its session secret and keep making new auth sessions, with every other request failing
 * `use_auth_http` in a config file being overridden by the default command line argument to `lbrynet-daemon`, now the command line value will only override the config file value if it is provided
 * `lbrynet-cli` not automatically switching to the authenticated client if the server is detected to be using authentication. This resulted in `lbrynet-cli` failing to run when `lbrynet-daemon` was run with the `--http-auth` flag
 * fixed error when using `claim_show` with `txid` and `nout` arguments
 * fixed error when saving server list to conf file ([1209](https://github.com/lbryio/lbry/pull/1209))

### Changed
 * if the `use_authentication` setting is configured, use authentication for all api methods instead of only those with the `auth_required` decorator
 * regenerate api keys on startup if the using authentication
 * support both positional and keyword args for api calls
 * `blob_announce` to queue the blob announcement but not block on it
 * `peer_list` to return a list of dictionaries instead of a list of lists, added peer node ids to the results
 * predictable result sorting for `claim_list` and `claim_list_mine` ([1216](https://github.com/lbryio/lbry/pull/1216) and [1208](https://github.com/lbryio/lbry/pull/1208))
 * increase the default `auto_re_reflect_interval` setting to a day and the default `concurrent_announcers` setting to 10
 * download blockchain headers from s3 before starting the wallet when the local height is more than `s3_headers_depth` (a config setting) blocks behind ([1177](https://github.com/lbryio/lbry/pull/1177))
 * check headers file integrity on startup, removing/truncating the file to force re-download when necessary
 * support partial headers file download from S3 ([1189](https://github.com/lbryio/lbry/pull/1189))
 * refactor `add_completed_blobs` on storage.py, simplifying into less queries ([1226](https://github.com/lbryio/lbry/pull/1226))
 * full verification of streams only during database migration instead of every startup ([1195](https://github.com/lbryio/lbry/pull/1195))
 * database batching functions for starting up the file manager
 * added `single_announce` and `last_announced_time` columns to the `blob` table in sqlite
 * track successful reflector uploads in sqlite to minimize how many streams are attempted by auto re-reflect ([1194](https://github.com/lbryio/lbry/pull/1194))
 * pass the sd hash to reflector ClientFactory instead of looking it up from the database
 * dht logging to be more verbose with errors and warnings
 * `store` kademlia rpc method to block on the call finishing and to return storing peer information
 * kademlia protocol to minimally delay writes to the UDP socket
 * several internal dht functions to use inlineCallbacks
 * `DHTHashAnnouncer` and `Node` manage functions to use `LoopingCall`s instead of scheduling with `callLater`.
 * refactored `DHTHashAnnouncer` to no longer use locks, use a `DeferredSemaphore` to limit concurrent announcers
 * decoupled `DiskBlobManager` from `DHTHashAnnouncer`, get blob hashes to announce from `SQLiteStorage`. The blob manager no longer announces blobs after they are completed, the hash announcer takes care of this now.
 * changed the bucket splitting condition in the dht routing table to be more aggressive
 * ping dht nodes who have stored to us periodically to determine whether we should include them as an active peer for the hash when we are queried. Nodes that are known to be not reachable by the node storing the record are no longer returned as peers by the storing node.
 * changed dht bootstrap join process to better populate the routing table initially
 * cache dht node tokens used during announcement to minimize the number of requests that are needed
 * implement BEP0005 dht rules to classify nodes as good, bad, or unknown and for when to add them to the routing table (http://www.bittorrent.org/beps/bep_0005.html)
 * refactored internal dht contact class to track failure counts/times, the time the contact last replied to us, and the time the node last requested something fom us ([1211](https://github.com/lbryio/lbry/pull/1211))
 * refactored dht iterativeFind
 * sort dht contacts returned by `findCloseNodes` in the routing table
 * `reactor` and `callLater`, `listenUDP`, and `resolve` functions to be configurable (to allow easier testing)
 * calls to get the current time to use `reactor.seconds` (to control callLater and LoopingCall timing in tests)
 * temporarily disabled data price negotiation, treat all data as free
 * disabled Cryptonator price feed
 * use `treq` instead of `txrequests` ([1191](https://github.com/lbryio/lbry/pull/1191))
 * updated `cryptography` version to 2.2.2
 * removed `pycrypto` dependency, replacing all calls to `cryptography`

### Added
 * `peer_ping` command
 * `--sort` option in `file_list` ([1174](https://github.com/lbryio/lbry/pull/1174))
 * `port` field to contacts returned by `routing_table_get`
 * configurable `concurrent_announcers` and `s3_headers_depth` settings
 * virtual kademlia network and mock udp transport for dht integration tests
 * functional tests for bootstrapping the dht, announcing and expiring hashes, finding and pinging nodes, protocol version 0/1 backwards/forwards compatibility, and rejoining the network
 * linux distro and desktop name added to analytics ([1218](https://github.com/lbryio/lbry/pull/1218))
 * certifi module for Twisted SSL verification on Windows ([1213](https://github.com/lbryio/lbry/pull/1213))
 * protocol version to dht requests and to the response from `findValue`

### Removed
 * `announce_all` argument from `blob_announce`
 * old `blob_announce_all` command
 * unused `--wallet` argument to `lbrynet-daemon`, which used to be to support `PTCWallet`.
 * `AuthJSONRPCServer.auth_required` decorator ([1161](https://github.com/lbryio/lbry/pull/1161))
 * `OptimizedTreeRoutingTable` class used by the dht node for the time being


## [0.19.3] - 2018-05-04
### Changed
 * download blockchain headers from s3 before starting the wallet when the local height is more than s3_headers_depth (a config setting) blocks behind (https://github.com/lbryio/lbry/pull/1177)
 * un-deprecated report_bug command (https://github.com/lbryio/lbry/commit/f8e418fb4448a3ed1531657f8b3c608fb568af85)

## [0.19.2] - 2018-03-28
### Fixed
 * incorrectly raised download cancelled error for already verified blob files
 * infinite loop where reflector client keeps trying to send failing blobs, which may be failing because they are invalid and thus will never be successfully received
 * docstring bugs for `stream_availability`, `channel_import`, and `blob_announce`

### Added
 * `blob_reflect` command to send specific blobs to a reflector server
 * unit test for docopt

### Removed
 * `flags` decorator from server.py as short flags are no longer used when using api/cli methods

### Changed
 * Bumped `lbryum` requirement to 3.2.1 [see changelog](https://github.com/lbryio/lbryum/blob/master/CHANGELOG.md#321---2018-03-28)

## [0.19.1] - 2018-03-20
### Fixed
 * Fixed the inconsistencies in API and CLI docstrings
 * `blob_announce` error when announcing a single blob
 * `blob_list` error when looking up blobs by stream or sd hash ([1126](https://github.com/lbryio/lbry/pull/1126))
 * Claiming a channel with the exact amount present in wallet would return a confusing error ([1107](https://github.com/lbryio/lbry/issues/1107))
 * Channel creation to use same bid logic as for claims ([1148](https://github.com/lbryio/lbry/pull/1148))

### Deprecated
 * `report_bug` jsonrpc command

### Changed
 * Bumped `lbryschema` requirement to 0.0.15 [see changelog](https://github.com/lbryio/lbryschema/blob/master/CHANGELOG.md#0015---2018-03-20)
 * Bumped `lbryum` requirement to 3.2.0 [see changelog](https://github.com/lbryio/lbryum/blob/master/CHANGELOG.md#320---2018-03-20)
 * Reflector server to periodically check and set `should_announce` for sd and head blobs instead of during each request
 * Reflector server to use `SQLiteStorage` to find needed blob hashes for a stream

### Added
 * Scripts to auto-generate documentation ([1128](https://github.com/lbryio/lbry/pull/1128))
 * Now updating new channel also takes into consideration the original bid amount, so now channel could be updated for wallet balance + the original bid amount ([1137](https://github.com/lbryio/lbry/pull/1137))
 * Forward-compatibility for upcoming DHT bencoding changes

### Removed
 * Short(single dashed) arguments for `lbrynet-cli`


## [0.19.0] - 2018-03-02
### Fixed
 * improper parsing of arguments to CLI settings_set (https://github.com/lbryio/lbry/issues/930)
 * unnecessarily verbose exchange rate error (https://github.com/lbryio/lbry/issues/984)
 * value error due to a race condition when saving to the claim cache (https://github.com/lbryio/lbry/issues/1013)
 * being unable to re-download updated content (https://github.com/lbryio/lbry/issues/951)
 * sending error messages for failed api requests
 * file manager startup being slow when handling thousands of files
 * handling decryption error for blobs encrypted with an invalid key
 * handling stream with no data blob (https://github.com/lbryio/lbry/issues/905)
 * fetching the external ip
 * `blob_list` returning an error with --uri parameter and incorrectly returning `[]` for streams where blobs are known (https://github.com/lbryio/lbry/issues/895)
 * `get` failing with a non-useful error message when given a uri for a channel claim
 * exception checking in several wallet unit tests
 * daemon not erring properly for non-numeric values being passed to the `bid` parameter for the `publish` method
 * `publish` command to allow updating claims with a `bid` amount higher than the wallet balance, so long as the amount is less than the wallet balance plus the bid amount of the claim being updated (https://github.com/lbryio/lbry/issues/748)
 * incorrect `blob_num` for the stream terminator blob, which would result in creating invalid streams. Such invalid streams are detected on startup and are automatically removed (https://github.com/lbryio/lbry/issues/1124)

### Deprecated
 * `channel_list_mine`, replaced with `channel_list`
 * `get_availability`, replaced with `stream_availability`

### Changed
 * dht tests to only be in one folder
 * config file format of `known_dht_nodes`, `lbryum_servers`, and `reflector_servers` to lists of `hostname:port` strings
 * startup of `lbrynet-daemon` to block on the wallet being unlocked if it is encrypted
 * `publish` to verify the claim schema before trying to make the claim and to return better error messages
 * `channel_list_mine` to be instead named `channel_list`
 * `channel_list` to include channels where the certificate info has been imported but the claim is not in the wallet
 * file objects returned by `file_list` and `get` to contain `claim_name` field instead of `name`
 * `name` filter parameter for `file_list`, `file_set_status`, `file_reflect`,  and `file_delete` to be named `claim_name`
 * `metadata` field in file objects returned by `file_list` and `get` to be a [Metadata object](https://github.com/lbryio/lbryschema/blob/master/lbryschema/proto/metadata.proto#L5)
 * assumption for time it takes to announce single hash from 1 second to 5 seconds
 * HTTP error codes for failed api requests, conform to http://www.jsonrpc.org/specification#error_object (previously http errors were set for jsonrpc errors)
 * api requests resulting in errors to return less verbose tracebacks
 * logging about streams to not include file names (only include sd hashes)
 * wallet info exchange to re-use addresses, this was a significant source of address bloat in the wallet
 * lbrynet to not manually save the wallet file and to let lbryum handle it
 * internals to use reworked lbryum `payto` command
 * dht `Node` class to re-attempt joining the network every 60 secs if no peers are known
 * lbrynet database and file manager to separate the creation of lbry files (from downloading or publishing) from the handling of a stream. All files have a stream, but not all streams may have a file. (https://github.com/lbryio/lbry/issues/1020)
 * manager classes to use new `SQLiteStorage` for database interaction. This class uses a single `lbrynet.sqlite` database file.

### Added
 * `lbrynet-console`, a tool to run or connect to lbrynet-daemon and launch an interactive python console with the api functions built in.
 * `--conf` CLI flag to specify an alternate config file
 * `peer_port`, `disable_max_key_fee`, `auto_renew_claim_height_delta`, `blockchain_name`, and `lbryum_servers` to configurable settings
 * `wallet_unlock` command (available during startup to unlock an encrypted wallet)
 * support for wallet encryption via new commands `wallet_decrypt` and `wallet_encrypt`
 * `channel_import`, `channel_export`, and `claim_renew` commands
 * `blob_availability` and `stream_availability` commands for debugging download issues
 * a new startup stage to indicate if the daemon is waiting for the `wallet_unlock` command.
 * `abandon_info` dictionary (containing `claim_name`, `claim_id`, `address`, `amount`, `balance_delta` and `nout`) for claims, supports, and updates returned by `transaction_list`
 * `permanent_url` string to `channel_list_mine`, `claim_list`, `claim_show`, `resolve` and `resolve_name` (see lbryio/lbryum#203)
 * `is_mine` boolean to `channel_list` results
 * `txid`, `nout`, `channel_claim_id`, `channel_claim_name`, `status`, `blobs_completed`, and `blobs_in_stream` fields to file objects returned by `file_list` and `get`
 * `txid`, `nout`, `channel_claim_id`, and `channel_claim_name` filters for `file` commands (`file_list`, `file_set_status`, `file_reflect`,  and `file_delete`)
 * unit tests for `SQLiteStorage` and updated old tests for relevant changes (https://github.com/lbryio/lbry/issues/1088)

### Removed
 * `seccure` and `gmpy` dependencies
 * support for positional arguments in cli `settings_set`. Now only accepts settings changes in the form `--setting_key=value`
 * `auto_re_reflect` setting from the conf file, use the `reflect_uploads` setting instead
 * `name` argument for `claim_show` command
 * `message` response field in file objects returned by `file_list` and `get`
 * `include_tip_info` argument from `transaction_list`, which will now always include tip information.
 * old and unused UI related code
 * unnecessary `TempBlobManager` class
 * old storage classes used by the file manager, wallet, and blob manager
 * old `.db` database files from the data directory

## [0.18.0] - 2017-11-08
### Fixed
 * Fixed amount of close nodes to add to list in case of extension to neighbouring k-buckets
 * Fixed external IP detection via jsonip.com (avoid detecting IPv6)
 * Fixed failing ConnectionManager unit test for parallel connections
 * Fixed race condition between `publish` and `channel_new`
 * Fixed incorrect response on attempting to delete blob twice
 * Fixed local node ID reporting in peer list

### Changed
 * Bumped `lbryschema` requirement to 0.0.14 [see changelog](https://github.com/lbryio/lbryschema/blob/master/CHANGELOG.md#0014---2017-11-08)
 * Bumped `lbryum` requirement to 3.1.11 [see changelog](https://github.com/lbryio/lbryum/blob/master/CHANGELOG.md#3111---2017-11-08)
 * Moved BLOB_SIZE from conf.py to MAX_BLOB_SIZE in blob/blob_file.py

### Added
 * Added `utxo_list` command to list unspent transaction outputs
 * Added redundant API server for currency conversion

### Removed
 * Removed some alternate methods of reading from blob files
 * Removed `@AuthJSONRPCServer.queued` decorator

## [0.17.1] - 2017-10-25
### Fixed
 * Fixed slow startup for nodes with many lbry files
 * Fixed setting the external ip on startup
 * Fixed session startup not blocking on joining the dht
 * Fixed several parsing bugs that prevented replacing dead dht contacts
 * Fixed lbryid length validation
 * Fixed an old print statement that polluted logs
 * Fixed rpc id length for dht requests

### Changed
 * Bumped `lbryschema` requirement to 0.0.13 [see changelog](https://github.com/lbryio/lbryschema/blob/master/CHANGELOG.md#0013---2017-10-25)
 * Bumped `lbryum` requirement to 3.1.10 [see changelog](https://github.com/lbryio/lbryum/blob/master/CHANGELOG.md#3110---2017-10-25)
 * Use the first port available for the peer and dht ports, starting with the provided values (defaults of 3333 and 4444). This allows multiple lbrynet instances in a LAN with UPnP.
 * Detect a UPnP redirect that didn't get cleaned up on a previous run and use it
 * Bumped jsonschema requirement to 2.6.0
 * Refactor some assert statements to accommodate the PYTHONOPTIMIZE flag set for Android.

### Added
 * Added `wallet_prefill_addresses` command, which distributes credits to multiple addresses


## [0.17.0] - 2017-10-12
### Fixed
 * Fixed handling cancelled blob and availability requests
 * Fixed redundant blob requests to a peer
 * Fixed https://github.com/lbryio/lbry/issues/923
 * Fixed concurrent reflects opening too many files
 * Fixed cases when reflecting would fail on error conditions
 * Fixed deadlocks from occuring during blob writes
 * Fixed and updated`lbrynet.tests.dht`
 * Fixed redundant dht id
 * Fixed dht `ping` method
 * Fixed raising remote exceptions in dht
 * Fixed hanging delayedCall in dht node class
 * Fixed logging error in dht when calling or receiving methods with no arguments
 * Fixed IndexError in routingTable.findCloseNodes which would cause an empty list to be returned
 * Fixed bug where last blob in a stream was not saved to blob manager

### Deprecated
 * Deprecated `blob_announce_all` JSONRPC command. Use `blob_announce` instead.

### Changed
 * Bumped `lbryschema` requirement to 0.0.12 [see changelog](https://github.com/lbryio/lbryschema/blob/master/CHANGELOG.md#0012---2017-10-12)
 * Bumped `lbryum` requirement to 3.1.9 [see changelog](https://github.com/lbryio/lbryum/blob/master/CHANGELOG.md#319---2017-10-12)
 * Announcing by head blob is turned on by default
 * Updated reflector server dns
 * Moved tests into the lbrynet package.

### Added
 * Added WAL pragma to sqlite3
 * Added unit tests for `BlobFile`
 * Use `hashlib` for sha384 instead of `pycrypto`
 * Use `cryptography` instead of `pycrypto` for blob encryption and decryption
 * Use `cryptography` for PKCS7 instead of doing it manually
 * Use `BytesIO` buffers instead of temp files when processing blobs
 * Refactored and pruned blob related classes into `lbrynet.blobs`
 * Changed several `assert`s to raise more useful errors
 * Added ability for reflector to store stream information for head blob announce
 * Added blob announcement information to API call status with session flag

### Removed
 * Removed `TempBlobFile`
 * Removed unused `EncryptedFileOpener`


## [0.16.3] - 2017-09-28
### Fixed
 * Fixed blob download history

### Changed
 * Improved download analytics
 * Improved download errors by distinguishing a data timeout from a sd timeout


## [0.16.2] - 2017-09-26
### Fixed
 * Fixed https://github.com/lbryio/lbry/issues/771 (handle when a certificate is missing for a signed claim in `claim_list_mine`)


## [0.16.1] - 2017-09-20
### Fixed
 * Fixed `transaction_list` doc string
 * Fixed ([in lbryum](https://github.com/lbryio/lbryum/pull/156)) batched queries responsible for making transaction and tip histories slow
 * Fixed daemon refusing to start if DNS cannot resolve lbry.io domain.

### Changed
 * Bumped `lbryum` requirement to 3.1.8 [see changelog](https://github.com/lbryio/lbryum/blob/master/CHANGELOG.md#318---2017-09-20)


## [0.16.0] - 2017-09-18
### Fixed
 * Fixed uncaught error when shutting down after a failed daemon startup
 * Fixed spelling error in documentation.

### Changed
 * Bumped `lbryschema` requirement to 0.0.11 [see changelog](https://github.com/lbryio/lbryschema/blob/master/CHANGELOG.md#0011---2017-09-18)
 * Bumped `lbryum` requirement to 3.1.7 [see changelog](https://github.com/lbryio/lbryum/blob/master/CHANGELOG.md#317---2017-09-18)
 * Updated exchange rate tests for the lbry.io api

### Added
 * Added option to announce head blob only if seeding
 * Added option to download by seeking head blob first
 * By default, option to download seeking head blob first is turned on
 * Added `include_tip_info` param to `transaction_list` API call


## [0.15.2] - 2017-09-07
### Changed
 * Use lbry.io exchange rate API instead of google finance


## [0.15.1] - 2017-08-22
### Changed
 * Bumped `lbryschema` requirement to 0.0.10 [see changelog](https://github.com/lbryio/lbryschema/blob/master/CHANGELOG.md#0010---2017-08-22)
 * Bumped `lbryum` requirement to 3.1.6 [see changelog](https://github.com/lbryio/lbryum/blob/master/CHANGELOG.md#316---2017-08-22)
 * Persist DHT node id

### Added
 * Android platform detection in lbrynet/conf.py
 * androidhelpers module for determining base file paths


## [0.15.0] - 2017-08-15
### Fixed
 * Fixed reflector server blocking the `received_blob` reply on the server announcing the blob to the dht
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



## [0.10.3] - 2017-05-23

### Added
 * Add decorator to support queueing api calls
 * Added force option to API command resolve


### Changed
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
 * Dont add expected payment to wallet when payment rate is 0
### Fixed
 * Fix restart procedure in DaemonControl
 * Create download directory if it doesn't exist
 * Fixed descriptor_get
 * Fixed API command descriptor_get
 * Fixed API command transaction_show
 * Fixed error handling for jsonrpc commands
 * Handle failure to decode claim cache file



## [0.9.1] - 2017-03-17
### Added
 * publish API command can take metadata fields as arguments
 * Added `reflect_uploads` config to disable reflecting on upload
 * Added `--version` flag
### Fixed
 * Fix wallet_public_key API command
 * Fixed jsonrpc_reflect()
 * Fixed api help return
### Changed
 * Removed `simplejson` dependency in favor of bulitin `json`



## [0.9.0rc17] - 2017-03-10
### Fixed
 * Added string comparison to ClaimOutpoint (needed to look things up by outpoint)
 * Remove unused API commands from daemon
 * Fix file filter `outpoint`
 * Made dictionary key names in API commmand outputs to be more consistent
### Added
 * Add file filters: `claim_id`, `outpoint`, and `rowid`
 * Make loggly logs less verbose
### Changed
 * Change file filter `uri` to `name` and return field `lbry_uri` to `name`
 * Refactor file_list, add `full_status` argument to populate resource intensive fields
 * Remove deprecated file commands: `get_lbry_files`, `get_lbry_file`, and `file_get`
 * Remove deprecated `delete_lbry_file` command
 * Return standard file json from `get`


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
### Changed
 * Add `file_get` by stream hash
 * Add utils.call_later to replace reactor.callLater

### Fixed
 * Fix unhandled error in `get`
 * Fix sd blob timeout handling in `get_availability`, return 0.0

## [0.8.5] - 2017-02-18
### Fixed
 * Fix result expected by ui from file_get for missing files

## [0.8.4] - 2017-02-17
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
 * Change EWOULDBLOCK error in DHT to warning. #481
 * mark peers as down if it fails download protocol
 * Made hash reannounce time to be adjustable to fix [#432](https://github.com/lbryio/lbry/issues/432)
 * Fix recursion depth error upon failed blob
 * Call stopProducing in reflector client file_sender when uploading is done
 * Ensure streams in stream_info_manager are saved in lbry_file_manager
 * Fixed file_delete not deleting data from stream_info_manager [#470](https://github.com/lbryio/lbry/issues/470)
 * Fixed upload of bug reports to Slack ([#472](https://github.com/lbryio/lbry/issues/472))
 * Fixed claim updates [#473](https://github.com/lbryio/lbry/issues/473)
 * Handle ConnectionLost error in reflector client
 * Fix updating a claim where the stream doesn't change
 * Fix claim_abandon

### Changed
 * Add blob_get, descriptor_get, and blob_delete
 * Add filter keyword args to blob_list
 * Refactor get_availability
 * Add optional peer search timeout, add peer_search_timeout setting
 * make connection manager unit testeable
 * Convert EncryptedFileDownloader to inlineCallbacks
 * Convert EncryptedFileManager to use inlineCallbacks
 * Convert Daemon._delete_lbry_file to inlineCallbacks
 * Add uri to stream reflector to de-obfuscate reflector logs
 * Simplify lbrynet.lbrynet_daemon.Publisher
 * Reflect streams in file manager looping call rather than in each file
 * Convert GetStream to inclineCallbacks
 * Change callback condition in GetStream to the first data blob completing
 * Add local and remote heights to blockchain status



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
