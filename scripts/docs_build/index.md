# LBRY JSON-RPC API Documentation

## blob_announce

```text
Announce blobs to the DHT

Args:
    'announce_all'  :  (bool)  announce all the blobs possessed by user
    'blob_hash'     :  (str)   announce a blob, specified by blob_hash
    'stream_hash'   :  (str)   announce all blobs associated with
                               stream_hash
    'sd_hash'       :  (str)   announce all blobs associated with
                               sd_hash and the sd_hash itself

Returns:
    (bool) true if successful
```

## blob_availability

```text
Get blob availability

Args:
    'blob_hash'       :  (str)  check availability for this blob hash
    'search_timeout'  :  (int)  how long to search for peers for the blob
                                in the dht
    'blob_timeout'    :  (int)  how long to try downloading from a peer

Returns:
    (dict) {
        "is_available": <bool, true if blob is available from a peer from peer list>
        "reachable_peers": ["<ip>:<port>"],
        "unreachable_peers": ["<ip>:<port>"]
    }
```

## blob_delete

```text
Delete a blob

Args:
    'blob_hash'  :  (str)  blob hash of the blob to delete

Returns:
    (str) Success/fail message
```

## blob_get

```text
Download and return a blob

Args:
    'blob_hash' (required)  :  (str)  blob hash of the blob to get
    'timeout'               :  (int)  timeout in number of seconds
    'encoding'              :  (str)  by default no attempt at decoding
                                      is made, can be set to one of the
                                      following decoders:
                                      'json'
    'payment_rate_manager'  :  (str)  if not given the default payment rate
                                      manager will be used.
                                      supported alternative rate managers:
                                      'only-free'

Returns:
    (str) Success/Fail message or (dict) decoded data
```

## blob_list

```text
Returns blob hashes. If not given filters, returns all blobs known by the blob manager

Args:
    'needed'       :  (bool)  only return needed blobs
    'finished'     :  (bool)  only return finished blobs
    'uri'          :  (str)   filter blobs by stream in a uri
    'stream_hash'  :  (str)   filter blobs by stream hash
    'sd_hash'      :  (str)   filter blobs by sd hash
    'page_size'    :  (int)   results page size
    'page'         :  (int)   page of results to return

Returns:
    (list) List of blob hashes
```

## blob_reflect_all

```text
Reflects all saved blobs

Args:
          None

Returns:
    (bool) true if successful
```

## block_show

```text
Get contents of a block

Args:
    'blockhash' (required)  :  (str)  hash of the block to look up
    'height' (required)     :  (int)  height of the block to look up

Returns:
    (dict) Requested block
```

## channel_export

```text
Export serialized channel signing information for a given certificate claim id

Args:
    'claim_id' (required)  :  (str)  Claim ID to export information about

Returns:
    (str) Serialized certificate information
```

## channel_import

```text
Import serialized channel signing information (to allow signing new claims to the channel)

Args:
    'serialized_certificate_info'  :  (str)  certificate info

Returns:
    (dict) Result dictionary
```

## channel_list

```text
Get certificate claim infos for channels that can be published to

Args:
          None

Returns:
    (list) ClaimDict, includes 'is_mine' field to indicate if the certificate claim
    is in the wallet.
```

## channel_new

```text
Generate a publisher key and create a new '@' prefixed certificate claim

Args:
    'channel_name' (required)  :  (str)    name of the channel prefixed with '@'
    'amount' (required)        :  (float)  bid amount on the channel

Returns:
    (dict) Dictionary containing result of the claim
    {
        'tx' : (str) hex encoded transaction
        'txid' : (str) txid of resulting claim
        'nout' : (int) nout of the resulting claim
        'fee' : (float) fee paid for the claim transaction
        'claim_id' : (str) claim ID of the resulting claim
    }
```

## claim_abandon

```text
Abandon a name and reclaim credits from the claim

Args:
    'claim_id'  :  (str)  claim_id of the claim to abandon
    'txid'      :  (str)  txid of the claim to abandon
    'nout'      :  (int)  nout of the claim to abandon

Returns:
    (dict) Dictionary containing result of the claim
    {
        txid : (str) txid of resulting transaction
        fee : (float) fee paid for the transaction
    }
```

## claim_list

```text
List current claims and information about them for a given name

Args:
    'name' (required)  :  (str)  name of the claim to list info about

Returns:
    (dict) State of claims assigned for the name
    {
        'claims': (list) list of claims for the name
        [
            {
            'amount': (float) amount assigned to the claim
            'effective_amount': (float) total amount assigned to the claim,
                                including supports
            'claim_id': (str) claim ID of the claim
            'height': (int) height of block containing the claim
            'txid': (str) txid of the claim
            'nout': (int) nout of the claim
            'permanent_url': (str) permanent url of the claim,
            'supports': (list) a list of supports attached to the claim
            'value': (str) the value of the claim
            },
        ]
        'supports_without_claims': (list) supports without any claims attached to them
        'last_takeover_height': (int) the height of last takeover for the name
    }
```

## claim_list_by_channel

```text
Get paginated claims in a channel specified by a channel uri

Args:
    'uri' (required)  :  (str)   uri of the channel
    'uris'            :  (list)  uris of the channel
    'page'            :  (int)   which page of results to return where page 1 is the first
                                 page, defaults to no pages
    'page_size'       :  (int)   number of results in a page, default of 10

Returns:
    {
         resolved channel uri: {
            If there was an error:
            'error': (str) error message

            'claims_in_channel': the total number of results for the channel,

            If a page of results was requested:
            'returned_page': page number returned,
            'claims_in_channel': [
                {
                    'absolute_channel_position': (int) claim index number in sorted list of
                                                 claims which assert to be part of the
                                                 channel
                    'address': (str) claim address,
                    'amount': (float) claim amount,
                    'effective_amount': (float) claim amount including supports,
                    'claim_id': (str) claim id,
                    'claim_sequence': (int) claim sequence number,
                    'decoded_claim': (bool) whether or not the claim value was decoded,
                    'height': (int) claim height,
                    'depth': (int) claim depth,
                    'has_signature': (bool) included if decoded_claim
                    'name': (str) claim name,
                    'supports: (list) list of supports [{'txid': (str) txid,
                                                         'nout': (int) nout,
                                                         'amount': (float) amount}],
                    'txid': (str) claim txid,
                    'nout': (str) claim nout,
                    'signature_is_valid': (bool), included if has_signature,
                    'value': ClaimDict if decoded, otherwise hex string
                }
            ],
        }
    }
```

## claim_list_mine

```text
List my name claims

Args:
          None

Returns:
    (list) List of name claims owned by user
    [
        {
            'address': (str) address that owns the claim
            'amount': (float) amount assigned to the claim
            'blocks_to_expiration': (int) number of blocks until it expires
            'category': (str) "claim", "update" , or "support"
            'claim_id': (str) claim ID of the claim
            'confirmations': (int) number of blocks of confirmations for the claim
            'expiration_height': (int) the block height which the claim will expire
            'expired': (bool) true if expired, false otherwise
            'height': (int) height of the block containing the claim
            'is_spent': (bool) true if claim is abandoned, false otherwise
            'name': (str) name of the claim
            'permanent_url': (str) permanent url of the claim,
            'txid': (str) txid of the cliam
            'nout': (int) nout of the claim
            'value': (str) value of the claim
        },
   ]
```

## claim_new_support

```text
Support a name claim

Args:
    'name' (required)      :  (str)    name of the claim to support
    'claim_id' (required)  :  (str)    claim_id of the claim to support
    'amount' (required)    :  (float)  amount of support

Returns:
    (dict) Dictionary containing result of the claim
    {
        txid : (str) txid of resulting support claim
        nout : (int) nout of the resulting support claim
        fee : (float) fee paid for the transaction
    }
```

## claim_renew

```text
Renew claim(s) or support(s)

Args:
    'outpoint' (required)  :  (str)  outpoint of the claim to renew
    'height' (required)    :  (str)  update claims expiring before or at this block height

Returns:
    (dict) Dictionary where key is the the original claim's outpoint and
    value is the result of the renewal
    {
        outpoint:{

            'tx' : (str) hex encoded transaction
            'txid' : (str) txid of resulting claim
            'nout' : (int) nout of the resulting claim
            'fee' : (float) fee paid for the claim transaction
            'claim_id' : (str) claim ID of the resulting claim
        },
    }
```

## claim_send_to_address

```text
Send a name claim to an address

Args:
    'claim_id' (required)  :  (str)  claim_id to send
    'address' (required)   :  (str)  address to send the claim to
    'amount'               :  (int)  Amount of credits to claim name for, defaults to the current amount
                                     on the claim

Returns:
    (dict) Dictionary containing result of the claim
    {
        'tx' : (str) hex encoded transaction
        'txid' : (str) txid of resulting claim
        'nout' : (int) nout of the resulting claim
        'fee' : (float) fee paid for the claim transaction
        'claim_id' : (str) claim ID of the resulting claim
    }
```

## claim_show

```text
Resolve claim info from txid/nout or with claim ID

Args:
    'txid'      :  (str)  look for claim with this txid, nout must
                          also be specified
    'nout'      :  (int)  look for claim with this nout, txid must
                          also be specified
    'claim_id'  :  (str)  look for claim with this claim id

Returns:
    (dict) Dictionary containing claim info as below,

    {
        'txid': (str) txid of claim
        'nout': (int) nout of claim
        'amount': (float) amount of claim
        'value': (str) value of claim
        'height' : (int) height of claim takeover
        'claim_id': (str) claim ID of claim
        'supports': (list) list of supports associated with claim
    }

    if claim cannot be resolved, dictionary as below will be returned

    {
        'error': (str) reason for error
    }
```

## cli_test_command

```text
This command is only for testing the CLI argument parsing
Args:
    'a_arg'               :  a    arg
    'b_arg'               :  b    arg
    'pos_arg' (required)  :  pos  arg
    'pos_args'            :  pos  args
    'pos_arg2'            :  pos  arg 2
    'pos_arg3'            :  pos  arg 3

Returns:
    pos args
```

## commands

```text
Return a list of available commands

Args:
          None

Returns:
    (list) list of available commands
```

## daemon_stop

```text
Stop lbrynet-daemon

Args:
          None

Returns:
    (string) Shutdown message
```

## file_delete

```text
Delete a LBRY file

Args:
    'delete_from_download_dir'  :  (bool)  delete file from download directory,
                                           instead of just deleting blobs
    'delete_all'                :  (bool)  if there are multiple matching files,
                                           allow the deletion of multiple files.
                                           Otherwise do not delete anything.
    'sd_hash'                   :  (str)   delete by file sd hash
    'file_name'                 :  (str)   delete by file name in downloads folder
    'stream_hash'               :  (str)   delete by file stream hash
    'rowid'                     :  (int)   delete by file row id
    'claim_id'                  :  (str)   delete by file claim id
    'txid'                      :  (str)   delete by file claim txid
    'nout'                      :  (int)   delete by file claim nout
    'claim_name'                :  (str)   delete by file claim name
    'channel_claim_id'          :  (str)   delete by file channel claim id
    'channel_name'              :  (str)   delete by file channel claim name

Returns:
    (bool) true if deletion was successful
```

## file_list

```text
List files limited by optional filters

Args:
    'sd_hash'           :  (str)   get file with matching sd hash
    'file_name'         :  (str)   get file with matching file name in the
                                   downloads folder
    'stream_hash'       :  (str)   get file with matching stream hash
    'rowid'             :  (int)   get file with matching row id
    'claim_id'          :  (str)   get file with matching claim id
    'outpoint'          :  (str)   get file with matching claim outpoint
    'txid'              :  (str)   get file with matching claim txid
    'nout'              :  (int)   get file with matching claim nout
    'channel_claim_id'  :  (str)   get file with matching channel claim id
    'channel_name'      :  (str)   get file with matching channel name
    'claim_name'        :  (str)   get file with matching claim name
    'full_status'       :  (bool)  full status, populate the
                                   'message' and 'size' fields

Returns:
    (list) List of files

    [
        {
            'completed': (bool) true if download is completed,
            'file_name': (str) name of file,
            'download_directory': (str) download directory,
            'points_paid': (float) credit paid to download file,
            'stopped': (bool) true if download is stopped,
            'stream_hash': (str) stream hash of file,
            'stream_name': (str) stream name ,
            'suggested_file_name': (str) suggested file name,
            'sd_hash': (str) sd hash of file,
            'download_path': (str) download path of file,
            'mime_type': (str) mime type of file,
            'key': (str) key attached to file,
            'total_bytes': (int) file size in bytes, None if full_status is false,
            'written_bytes': (int) written size in bytes,
            'blobs_completed': (int) num_completed, None if full_status is false,
            'blobs_in_stream': (int) None if full_status is false,
            'status': (str) downloader status, None if full_status is false,
            'claim_id': (str) None if full_status is false or if claim is not found,
            'outpoint': (str) None if full_status is false or if claim is not found,
            'txid': (str) None if full_status is false or if claim is not found,
            'nout': (int) None if full_status is false or if claim is not found,
            'metadata': (dict) None if full_status is false or if claim is not found,
            'channel_claim_id': (str) None if full_status is false or if claim is not found or signed,
            'channel_name': (str) None if full_status is false or if claim is not found or signed,
            'claim_name': (str) None if full_status is false or if claim is not found
        },
    ]
```

## file_reflect

```text
Reflect all the blobs in a file matching the filter criteria

Args:
    'sd_hash'      :  (str)  get file with matching sd hash
    'file_name'    :  (str)  get file with matching file name in the
                             downloads folder
    'stream_hash'  :  (str)  get file with matching stream hash
    'rowid'        :  (int)  get file with matching row id
    'reflector'    :  (str)  reflector server, ip address or url
                             by default choose a server from the config

Returns:
    (list) list of blobs reflected
```

## file_set_status

```text
Start or stop downloading a file

Args:
    'status' (required)  :  (str)  one of "start" or "stop"
    'sd_hash'            :  (str)  set status of file with matching sd hash
    'file_name'          :  (str)  set status of file with matching file name in the
                                   downloads folder
    'stream_hash'        :  (str)  set status of file with matching stream hash
    'rowid'              :  (int)  set status of file with matching row id

Returns:
    (str) Confirmation message
```

## get

```text
Download stream from a LBRY name.

Args:
    'uri'        :  (str)  uri of the content to download
    'file_name'  :  (str)  specified name for the downloaded file
    'timeout'    :  (int)  download timeout in number of seconds

Returns:
    (dict) Dictionary containing information about the stream
    {
        'completed': (bool) true if download is completed,
        'file_name': (str) name of file,
        'download_directory': (str) download directory,
        'points_paid': (float) credit paid to download file,
        'stopped': (bool) true if download is stopped,
        'stream_hash': (str) stream hash of file,
        'stream_name': (str) stream name ,
        'suggested_file_name': (str) suggested file name,
        'sd_hash': (str) sd hash of file,
        'download_path': (str) download path of file,
        'mime_type': (str) mime type of file,
        'key': (str) key attached to file,
        'total_bytes': (int) file size in bytes, None if full_status is false,
        'written_bytes': (int) written size in bytes,
        'blobs_completed': (int) num_completed, None if full_status is false,
        'blobs_in_stream': (int) None if full_status is false,
        'status': (str) downloader status, None if full_status is false,
        'claim_id': (str) claim id,
        'outpoint': (str) claim outpoint string,
        'txid': (str) claim txid,
        'nout': (int) claim nout,
        'metadata': (dict) claim metadata,
        'channel_claim_id': (str) None if claim is not signed
        'channel_name': (str) None if claim is not signed
        'claim_name': (str) claim name
    }
```

## help

```text
Return a useful message for an API command

Args:
    'command'  :  (str)  command to retrieve documentation for

Returns:
    (str) Help message
```

## peer_list

```text
Get peers for blob hash

Args:
    'blob_hash' (required)  :  (str)  find available peers for this blob hash
    'timeout'               :  (int)  peer search timeout in seconds

Returns:
    (list) List of contacts
```

## publish

```text
Make a new name claim and publish associated data to lbrynet,
update over existing claim if user already has a claim for name.

Fields required in the final Metadata are:
    'title'
    'description'
    'author'
    'language'
    'license'
    'nsfw'

Metadata can be set by either using the metadata argument or by setting individual arguments
fee, title, description, author, language, license, license_url, thumbnail, preview, nsfw,
or sources. Individual arguments will overwrite the fields specified in metadata argument.

Args:
    'name' (required)  :  (str)    name of the content
    'bid' (required)   :  (float)  amount to back the claim
    'metadata'         :  (dict)   ClaimDict to associate with the claim.
    'file_path'        :  (str)    path to file to be associated with name. If provided,
                                   a lbry stream of this file will be used in 'sources'.
                                   If no path is given but a sources dict is provided,
                                   it will be used. If neither are provided, an
                                   error is raised.
    'fee'              :  (dict)   Dictionary representing key fee to download content:
                                   {
                                   'currency': currency_symbol,
                                   'amount': float,
                                   'address': str, optional
                                   }
                                   supported currencies: LBC, USD, BTC
                                   If an address is not provided a new one will be
                                   automatically generated. Default fee is zero.
    'title'            :  (str)    title of the publication
    'description'      :  (str)    description of the publication
    'author'           :  (str)    author of the publication
    'language'         :  (str)    language of the publication
    'license'          :  (str)    publication license
    'license_url'      :  (str)    publication license url
    'thumbnail'        :  (str)    thumbnail url
    'preview'          :  (str)    preview url
    'nsfw'             :  (bool)   title of the publication
    'sources'          :  (str)    {'lbry_sd_hash': sd_hash} specifies sd hash of file
    'channel_name'     :  (str)    name of the publisher channel name in the wallet
    'channel_id'       :  (str)    claim id of the publisher channel, does not check
                                   for channel claim being in the wallet. This allows
                                   publishing to a channel where only the certificate
                                   private key is in the wallet.
    'claim_address'    :  (str)    address where the claim is sent to, if not specified
                                   new address wil automatically be created

Returns:
    (dict) Dictionary containing result of the claim
    {
        'tx' : (str) hex encoded transaction
        'txid' : (str) txid of resulting claim
        'nout' : (int) nout of the resulting claim
        'fee' : (float) fee paid for the claim transaction
        'claim_id' : (str) claim ID of the resulting claim
    }
```

## resolve

```text
Resolve given LBRY URIs

Args:
    'force'           :  (bool)  force refresh and ignore cache
    'uri' (required)  :  (str)   uri to resolve
    'uris'            :  (list)  uris to resolve

Returns:
    Dictionary of results, keyed by uri
    '<uri>': {
            If a resolution error occurs:
            'error': Error message

            If the uri resolves to a channel or a claim in a channel:
            'certificate': {
                'address': (str) claim address,
                'amount': (float) claim amount,
                'effective_amount': (float) claim amount including supports,
                'claim_id': (str) claim id,
                'claim_sequence': (int) claim sequence number,
                'decoded_claim': (bool) whether or not the claim value was decoded,
                'height': (int) claim height,
                'depth': (int) claim depth,
                'has_signature': (bool) included if decoded_claim
                'name': (str) claim name,
                'permanent_url': (str) permanent url of the certificate claim,
                'supports: (list) list of supports [{'txid': (str) txid,
                                                     'nout': (int) nout,
                                                     'amount': (float) amount}],
                'txid': (str) claim txid,
                'nout': (str) claim nout,
                'signature_is_valid': (bool), included if has_signature,
                'value': ClaimDict if decoded, otherwise hex string
            }

            If the uri resolves to a channel:
            'claims_in_channel': (int) number of claims in the channel,

            If the uri resolves to a claim:
            'claim': {
                'address': (str) claim address,
                'amount': (float) claim amount,
                'effective_amount': (float) claim amount including supports,
                'claim_id': (str) claim id,
                'claim_sequence': (int) claim sequence number,
                'decoded_claim': (bool) whether or not the claim value was decoded,
                'height': (int) claim height,
                'depth': (int) claim depth,
                'has_signature': (bool) included if decoded_claim
                'name': (str) claim name,
                'permanent_url': (str) permanent url of the claim,
                'channel_name': (str) channel name if claim is in a channel
                'supports: (list) list of supports [{'txid': (str) txid,
                                                     'nout': (int) nout,
                                                     'amount': (float) amount}]
                'txid': (str) claim txid,
                'nout': (str) claim nout,
                'signature_is_valid': (bool), included if has_signature,
                'value': ClaimDict if decoded, otherwise hex string
            }
    }
```

## resolve_name

```text
Resolve stream info from a LBRY name

Args:
    'name' (required)  :  (str)   the name to resolve
    'force'            :  (bool)  force refresh and do not check cache

Returns:
    (dict) Metadata dictionary from name claim, None if the name is not
            resolvable
```

## routing_table_get

```text
Get DHT routing information

Args:
          None

Returns:
    (dict) dictionary containing routing and contact information
    {
        "buckets": {
            <bucket index>: [
                {
                    "address": (str) peer address,
                    "node_id": (str) peer node id,
                    "blobs": (list) blob hashes announced by peer
                }
            ]
        },
        "contacts": (list) contact node ids,
        "blob_hashes": (list) all of the blob hashes stored by peers in the list of buckets,
        "node_id": (str) the local dht node id
    }
```

## settings_get

```text
Get daemon settings

Args:
          None

Returns:
    (dict) Dictionary of daemon settings
    See ADJUSTABLE_SETTINGS in lbrynet/conf.py for full list of settings
```

## settings_set

```text
Set daemon settings

Args:
    'download_directory'             :  (str)    path of download directory
    'data_rate'                      :  (float)  0.0001
    'download_timeout'               :  (int)    180
    'peer_port'                      :  (int)    3333
    'max_key_fee'                    :  (dict)   maximum key fee for downloads,
                                                 in the format:
                                                 {
                                                 'currency': <currency_symbol>,
                                                 'amount': <amount>
                                                 }.
                                                 In the CLI, it must be an escaped JSON string
                                                 Supported currency symbols: LBC, USD, BTC
    'disable_max_key_fee'            :  (bool)   False
    'use_upnp'                       :  (bool)   True
    'run_reflector_server'           :  (bool)   False
    'cache_time'                     :  (int)    150
    'reflect_uploads'                :  (bool)   True
    'share_usage_data'               :  (bool)   True
    'peer_search_timeout'            :  (int)    3
    'sd_download_timeout'            :  (int)    3
    'auto_renew_claim_height_delta'  :  (int)    0
                                                 claims set to expire within this many blocks will be
                                                 automatically renewed after startup (if set to 0, renews
                                                 will not be made automatically)

Returns:
    (dict) Updated dictionary of daemon settings
```

## status

```text
Get daemon status

Args:
    'session_status'  :  (bool)  include session status in results
    'dht_status'      :  (bool)  include dht network and peer status

Returns:
    (dict) lbrynet-daemon status
    {
        'lbry_id': lbry peer id, base58,
        'installation_id': installation id, base58,
        'is_running': bool,
        'is_first_run': bool,
        'startup_status': {
            'code': status code,
            'message': status message
        },
        'connection_status': {
            'code': connection status code,
            'message': connection status message
        },
        'blockchain_status': {
            'blocks': local blockchain height,
            'blocks_behind': remote_height - local_height,
            'best_blockhash': block hash of most recent block,
        },
        'wallet_is_encrypted': bool,

        If given the session status option:
            'session_status': {
                'managed_blobs': count of blobs in the blob manager,
                'managed_streams': count of streams in the file manager
                'announce_queue_size': number of blobs currently queued to be announced
                'should_announce_blobs': number of blobs that should be announced
            }

        If given the dht status option:
            'dht_status': {
                'kbps_received': current kbps receiving,
                'kbps_sent': current kdps being sent,
                'total_bytes_sent': total bytes sent,
                'total_bytes_received': total bytes received,
                'queries_received': number of queries received per second,
                'queries_sent': number of queries sent per second,
                'recent_contacts': count of recently contacted peers,
                'unique_contacts': count of unique peers
            },
    }
```

## stream_availability

```text
Get stream availability for lbry uri

Args:
    'uri' (required)  :  (str)  check availability for this uri
    'search_timeout'  :  (int)  how long to search for peers for the blob
                                in the dht
    'search_timeout'  :  (int)  how long to try downloading from a peer

Returns:
    (dict) {
        'is_available': <bool>,
        'did_decode': <bool>,
        'did_resolve': <bool>,
        'is_stream': <bool>,
        'num_blobs_in_stream': <int>,
        'sd_hash': <str>,
        'sd_blob_availability': <dict> see `blob_availability`,
        'head_blob_hash': <str>,
        'head_blob_availability': <dict> see `blob_availability`,
        'use_upnp': <bool>,
        'upnp_redirect_is_set': <bool>,
        'error': <None> | <str> error message
    }
```

## stream_cost_estimate

```text
Get estimated cost for a lbry stream

Args:
    'uri' (required)  :  (str)    uri to use
    'size'            :  (float)  stream size in bytes. if provided an sd blob won't be
                                  downloaded.

Returns:
    (float) Estimated cost in lbry credits, returns None if uri is not
        resolvable
```

## transaction_list

```text
List transactions belonging to wallet

Args:
          None

Returns:
    (list) List of transactions

    {
        "claim_info": (list) claim info if in txn [{
                                                "address": (str) address of claim,
                                                "balance_delta": (float) bid amount,
                                                "amount": (float) claim amount,
                                                "claim_id": (str) claim id,
                                                "claim_name": (str) claim name,
                                                "nout": (int) nout
                                                }],
        "abandon_info": (list) abandon info if in txn [{
                                                "address": (str) address of abandoned claim,
                                                "balance_delta": (float) returned amount,
                                                "amount": (float) claim amount,
                                                "claim_id": (str) claim id,
                                                "claim_name": (str) claim name,
                                                "nout": (int) nout
                                                }],
        "confirmations": (int) number of confirmations for the txn,
        "date": (str) date and time of txn,
        "fee": (float) txn fee,
        "support_info": (list) support info if in txn [{
                                                "address": (str) address of support,
                                                "balance_delta": (float) support amount,
                                                "amount": (float) support amount,
                                                "claim_id": (str) claim id,
                                                "claim_name": (str) claim name,
                                                "is_tip": (bool),
                                                "nout": (int) nout
                                                }],
        "timestamp": (int) timestamp,
        "txid": (str) txn id,
        "update_info": (list) update info if in txn [{
                                                "address": (str) address of claim,
                                                "balance_delta": (float) credited/debited
                                                "amount": (float) absolute amount,
                                                "claim_id": (str) claim id,
                                                "claim_name": (str) claim name,
                                                "nout": (int) nout
                                                }],
        "value": (float) value of txn
    }
```

## transaction_show

```text
Get a decoded transaction from a txid

Args:
    'txid' (required)  :  (str)  txid of the transaction

Returns:
    (dict) JSON formatted transaction
```

## utxo_list

```text
List unspent transaction outputs

Args:
          None

Returns:
    (list) List of unspent transaction outputs (UTXOs)
    [
        {
            "address": (str) the output address
            "amount": (float) unspent amount
            "height": (int) block height
            "is_claim": (bool) is the tx a claim
            "is_coinbase": (bool) is the tx a coinbase tx
            "is_support": (bool) is the tx a support
            "is_update": (bool) is the tx an update
            "nout": (int) nout of the output
            "txid": (str) txid of the output
        },
        ...
    ]
```

## version

```text
Get lbry version information

Args:
          None

Returns:
    (dict) Dictionary of lbry version information
    {
        'build': (str) build type (e.g. "dev", "rc", "release"),
        'ip': (str) remote ip, if available,
        'lbrynet_version': (str) lbrynet_version,
        'lbryum_version': (str) lbryum_version,
        'lbryschema_version': (str) lbryschema_version,
        'os_release': (str) os release string
        'os_system': (str) os name
        'platform': (str) platform string
        'processor': (str) processor type,
        'python_version': (str) python version,
    }
```

## wallet_balance

```text
Return the balance of the wallet

Args:
    'address'              :  (str)   If provided only the balance for this
                                      address will be given
    'include_unconfirmed'  :  (bool)  Include unconfirmed

Returns:
    (float) amount of lbry credits in wallet
```

## wallet_decrypt

```text
Decrypt an encrypted wallet, this will remove the wallet password

Args:
          None

Returns:
    (bool) true if wallet is decrypted, otherwise false
```

## wallet_encrypt

```text
Encrypt a wallet with a password, if the wallet is already encrypted this will update
the password

Args:
    'new_password' (required)  :  (str)  password string to be used for encrypting wallet

Returns:
    (bool) true if wallet is decrypted, otherwise false
```

## wallet_is_address_mine

```text
Checks if an address is associated with the current wallet.

Args:
    'address' (required)  :  (str)  address to check

Returns:
    (bool) true, if address is associated with current wallet
```

## wallet_list

```text
List wallet addresses

Args:
          None

Returns:
    List of wallet addresses
```

## wallet_new_address

```text
Generate a new wallet address

Args:
          None

Returns:
    (str) New wallet address in base58
```

## wallet_prefill_addresses

```text
Create new addresses, each containing `amount` credits

Args:
    'no_broadcast'              :  (bool)   whether to broadcast or not
    'num_addresses' (required)  :  (int)    num of addresses to create
    'amount' (required)         :  (float)  initial amount in each address

Returns:
    (dict) the resulting transaction
```

## wallet_public_key

```text
Get public key from wallet address

Args:
    'address' (required)  :  (str)  address for which to get the public key

Returns:
    (list) list of public keys associated with address.
        Could contain more than one public key if multisig.
```

## wallet_send

```text
Send credits. If given an address, send credits to it. If given a claim id, send a tip
to the owner of a claim specified by uri. A tip is a claim support where the recipient
of the support is the claim address for the claim being supported.

Args:
    'amount' (required)    :  (float)  amount of credit to send
    'address' (required)   :  (str)    address to send credits to
    'claim_id' (required)  :  (float)  claim_id of the claim to send to tip to

Returns:
    If sending to an address:
    (bool) true if payment successfully scheduled

    If sending a claim tip:
    (dict) Dictionary containing the result of the support
    {
        txid : (str) txid of resulting support claim
        nout : (int) nout of the resulting support claim
        fee : (float) fee paid for the transaction
    }
```

## wallet_unlock

```text
Unlock an encrypted wallet

Args:
    'password' (required)  :  (str)  password for unlocking wallet

Returns:
    (bool) true if wallet is unlocked, otherwise false
```

## wallet_unused_address

```text
Return an address containing no balance, will create
a new address if there is none.

Args:
          None

Returns:
    (str) Unused wallet address in base58
```

