# LBRY Command Line Documentation

## blob_announce

```text
Announce blobs to the DHT

Usage:
    blob_announce [-a] [<blob_hash> | --blob_hash=<blob_hash>]
                  [<stream_hash> | --stream_hash=<stream_hash>]
                  [<sd_hash> | --sd_hash=<sd_hash>]

Options:
    -a                                          : announce all the blobs possessed by user
    <blob_hash>, --blob_hash=<blob_hash>        : announce a blob, specified by blob_hash
    <stream_hash>, --stream_hash=<stream_hash>  : announce all blobs associated with
                                                    stream_hash
    <sd_hash>, --sd_hash=<sd_hash>              : announce all blobs associated with
                                                    sd_hash and the sd_hash itself

Returns:
    (bool) true if successful
```

## blob_announce_all

```text
Announce all blobs to the DHT

Usage:
    blob_announce_all

Returns:
    (str) Success/fail message
```

## blob_delete

```text
Delete a blob

Usage:
    blob_delete (<blob_hash> | --blob_hash=<blob_hash)

Returns:
    (str) Success/fail message
```

## blob_get

```text
Download and return a blob

Usage:
    blob_get (<blob_hash> | --blob_hash=<blob_hash>) [--timeout=<timeout>]
             [--encoding=<encoding>] [--payment_rate_manager=<payment_rate_manager>]

Options:
--timeout=<timeout>                            : timeout in number of seconds
--encoding=<encoding>                          : by default no attempt at decoding is made,
                                                 can be set to one of the
                                                 following decoders:
                                                    'json'
--payment_rate_manager=<payment_rate_manager>  : if not given the default payment rate
                                                 manager will be used.
                                                 supported alternative rate managers:
                                                    'only-free'

Returns
    (str) Success/Fail message or (dict) decoded data
```

## blob_list

```text
Returns blob hashes. If not given filters, returns all blobs known by the blob manager

Usage:
    blob_list [-n] [-f] [<uri> | --uri=<uri>] [<stream_hash> | --stream_hash=<stream_hash>]
              [<sd_hash> | --sd_hash=<sd_hash>] [<page_size> | --page_size=<page_size>]
              [<page> | --page=<page>]

Options:
    -n                                          : only return needed blobs
    -f                                          : only return finished blobs
    <uri>, --uri=<uri>                          : filter blobs by stream in a uri
    <stream_hash>, --stream_hash=<stream_hash>  : filter blobs by stream hash
    <sd_hash>, --sd_hash=<sd_hash>              : filter blobs by sd hash
    <page_size>, --page_size=<page_size>        : results page size
    <page>, --page=<page>                       : page of results to return

Returns:
    (list) List of blob hashes
```

## blob_reflect_all

```text
Reflects all saved blobs

Usage:
    blob_reflect_all

Returns:
    (bool) true if successful
```

## block_show

```text
Get contents of a block

Usage:
    block_show (<blockhash> | --blockhash=<blockhash>) | (<height> | --height=<height>)

Options:
    <blockhash>, --blockhash=<blockhash>  : hash of the block to look up
    <height>, --height=<height>           : height of the block to look up

Returns:
    (dict) Requested block
```

## channel_list_mine

```text
Get my channels

Usage:
    channel_list_mine

Returns:
    (list) ClaimDict
```

## channel_new

```text
Generate a publisher key and create a new '@' prefixed certificate claim

Usage:
    channel_new (<channel_name> | --channel_name=<channel_name>)
                (<amount> | --amount=<amount>)

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

Usage:
    claim_abandon [<claim_id> | --claim_id=<claim_id>]
                  [<txid> | --txid=<txid>] [<nout> | --nout=<nout>]

Return:
    (dict) Dictionary containing result of the claim
    {
        txid : (str) txid of resulting transaction
        fee : (float) fee paid for the transaction
    }
```

## claim_list

```text
List current claims and information about them for a given name

Usage:
    claim_list (<name> | --name=<name>)

Returns
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

Usage:
    claim_list_by_channel (<uri> | --uri=<uri>) [<uris>...] [--page=<page>]
                           [--page_size=<page_size>]

Options:
    --page=<page>            : which page of results to return where page 1 is the first
                               page, defaults to no pages
    --page_size=<page_size>  : number of results in a page, default of 10

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
                    'supports: (list) list of supports [{'txid': txid,
                                                         'nout': nout,
                                                         'amount': amount}],
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

Usage:
    claim_list_mine

Returns
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
            'txid': (str) txid of the cliam
            'nout': (int) nout of the claim
            'value': (str) value of the claim
        },
   ]
```

## claim_new_support

```text
Support a name claim

Usage:
    claim_new_support (<name> | --name=<name>) (<claim_id> | --claim_id=<claim_id>)
                      (<amount> | --amount=<amount>)

Return:
    (dict) Dictionary containing result of the claim
    {
        txid : (str) txid of resulting support claim
        nout : (int) nout of the resulting support claim
        fee : (float) fee paid for the transaction
    }
```

## claim_send_to_address

```text
Send a name claim to an address

Usage:
    claim_send_to_address (<claim_id> | --claim_id=<claim_id>)
                          (<address> | --address=<address>)
                          [<amount> | --amount=<amount>]

Options:
    <amount>  : Amount of credits to claim name for, defaults to the current amount
                on the claim
```

## claim_show

```text
Resolve claim info from txid/nout or with claim ID

Usage:
    claim_show [<txid> | --txid=<txid>] [<nout> | --nout=<nout>]
               [<claim_id> | --claim_id=<claim_id>]

Options:
    <txid>, --txid=<txid>              : look for claim with this txid, nout must
                                            also be specified
    <nout>, --nout=<nout>              : look for claim with this nout, txid must
                                            also be specified
    <claim_id>, --claim_id=<claim_id>  : look for claim with this claim id

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
Usage:
    cli_test_command [-a] [-b] (<pos_arg> | --pos_arg=<pos_arg>)
                     [<pos_args>...] [--pos_arg2=<pos_arg2>]
                     [--pos_arg3=<pos_arg3>]

Options:
    -a, --a_arg                        : a arg
    -b, --b_arg                        : b arg
    <pos_arg2>, --pos_arg2=<pos_arg2>  : pos arg 2
    <pos_arg3>, --pos_arg3=<pos_arg3>  : pos arg 3
Returns:
    pos args
```

## commands

```text
Return a list of available commands

Usage:
    commands

Returns:
    (list) list of available commands
```

## daemon_stop

```text
Stop lbrynet-daemon

Usage:
    daemon_stop

Returns:
    (string) Shutdown message
```

## file_delete

```text
Delete a LBRY file

Usage:
    file_delete [-f] [--delete_all] [--sd_hash=<sd_hash>] [--file_name=<file_name>]
                [--stream_hash=<stream_hash>] [--claim_id=<claim_id>]
                [--outpoint=<outpoint>] [--rowid=<rowid>]
                [--name=<name>]

Options:
    -f, --delete_from_download_dir  : delete file from download directory,
                                        instead of just deleting blobs
    --delete_all                    : if there are multiple matching files,
                                        allow the deletion of multiple files.
                                        Otherwise do not delete anything.
    --sd_hash=<sd_hash>             : delete by file sd hash
    --file_name<file_name>          : delete by file name in downloads folder
    --stream_hash=<stream_hash>     : delete by file stream hash
    --claim_id=<claim_id>           : delete by file claim id
    --outpoint=<outpoint>           : delete by file claim outpoint
    --rowid=<rowid>                 : delete by file row id
    --name=<name>                   : delete by associated name claim of file

Returns:
    (bool) true if deletion was successful
```

## file_list

```text
List files limited by optional filters

Usage:
    file_list [--sd_hash=<sd_hash>] [--file_name=<file_name>] [--stream_hash=<stream_hash>]
              [--claim_id=<claim_id>] [--outpoint=<outpoint>] [--rowid=<rowid>]
              [--name=<name>]
              [-f]

Options:
    --sd_hash=<sd_hash>          : get file with matching sd hash
    --file_name=<file_name>      : get file with matching file name in the
                                   downloads folder
    --stream_hash=<stream_hash>  : get file with matching stream hash
    --claim_id=<claim_id>        : get file with matching claim id
    --outpoint=<outpoint>        : get file with matching claim outpoint
    --rowid=<rowid>              : get file with matching row id
    --name=<name>                : get file with matching associated name claim
    -f                           : full status, populate the 'message' and 'size' fields

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
            'name': (str) name claim attached to file
            'outpoint': (str) claim outpoint attached to file
            'claim_id': (str) claim ID attached to file,
            'download_path': (str) download path of file,
            'mime_type': (str) mime type of file,
            'key': (str) key attached to file,
            'total_bytes': (int) file size in bytes, None if full_status is false
            'written_bytes': (int) written size in bytes
            'message': (str), None if full_status is false
            'metadata': (dict) Metadata dictionary
        },
    ]
```

## file_reflect

```text
Reflect all the blobs in a file matching the filter criteria

Usage:
    file_reflect [--sd_hash=<sd_hash>] [--file_name=<file_name>]
                 [--stream_hash=<stream_hash>] [--claim_id=<claim_id>]
                 [--outpoint=<outpoint>] [--rowid=<rowid>] [--name=<name>]
                 [--reflector=<reflector>]

Options:
    --sd_hash=<sd_hash>          : get file with matching sd hash
    --file_name=<file_name>      : get file with matching file name in the
                                   downloads folder
    --stream_hash=<stream_hash>  : get file with matching stream hash
    --claim_id=<claim_id>        : get file with matching claim id
    --outpoint=<outpoint>        : get file with matching claim outpoint
    --rowid=<rowid>              : get file with matching row id
    --name=<name>                : get file with matching associated name claim
    --reflector=<reflector>      : reflector server, ip address or url
                                   by default choose a server from the config

Returns:
    (list) list of blobs reflected
```

## file_set_status

```text
Start or stop downloading a file

Usage:
    file_set_status <status> [--sd_hash=<sd_hash>] [--file_name=<file_name>]
              [--stream_hash=<stream_hash>] [--claim_id=<claim_id>]
              [--outpoint=<outpoint>] [--rowid=<rowid>]
              [--name=<name>]

Options:
    --sd_hash=<sd_hash>          : set status of file with matching sd hash
    --file_name=<file_name>      : set status of file with matching file name in the
                                   downloads folder
    --stream_hash=<stream_hash>  : set status of file with matching stream hash
    --claim_id=<claim_id>        : set status of file with matching claim id
    --outpoint=<outpoint>        : set status of file with matching claim outpoint
    --rowid=<rowid>              : set status of file with matching row id
    --name=<name>                : set status of file with matching associated name claim

Returns:
    (str) Confirmation message
```

## get

```text
Download stream from a LBRY name.

Usage:
    get <uri> [<file_name> | --file_name=<file_name>] [<timeout> | --timeout=<timeout>]


Options:
    <file_name>           : specified name for the downloaded file
    <timeout>             : download timeout in number of seconds
    <download_directory>  : path to directory where file will be saved

Returns:
    (dict) Dictionary contaning information about the stream
    {
        'completed': (bool) true if download is completed,
        'file_name': (str) name of file,
        'download_directory': (str) download directory,
        'points_paid': (float) credit paid to download file,
        'stopped': (bool) true if download is stopped,
        'stream_hash': (str) stream hash of file,
        'stream_name': (str) stream name,
        'suggested_file_name': (str) suggested file name,
        'sd_hash': (str) sd hash of file,
        'name': (str) name claim attached to file
        'outpoint': (str) claim outpoint attached to file
        'claim_id': (str) claim ID attached to file,
        'download_path': (str) download path of file,
        'mime_type': (str) mime type of file,
        'key': (str) key attached to file,
        'total_bytes': (int) file size in bytes, None if full_status is false
        'written_bytes': (int) written size in bytes
        'message': (str), None if full_status is false
        'metadata': (dict) Metadata dictionary
    }
```

## get_availability

```text
Get stream availability for lbry uri

Usage:
    get_availability (<uri> | --uri=<uri>) [<sd_timeout> | --sd_timeout=<sd_timeout>]
                     [<peer_timeout> | --peer_timeout=<peer_timeout>]

Options:
    <sd_timeout>, --sd_timeout=<sd_timeout>        : sd blob download timeout
    <peer_timeout>, --peer_timeout=<peer_timeout>  : how long to look for peers

Returns:
    (float) Peers per blob / total blobs
```

## help

```text
Return a useful message for an API command

Usage:
    help [<command> | --command=<command>]

Options:
    <command>, --command=<command>  : command to retrieve documentation for
```

## peer_list

```text
Get peers for blob hash

Usage:
    peer_list (<blob_hash> | --blob_hash=<blob_hash>) [<timeout> | --timeout=<timeout>]

Options:
    <timeout>, --timeout=<timeout>  : peer search timeout in seconds

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

Usage:
    publish (<name> | --name=<name>) (<bid> | --bid=<bid>) [--metadata=<metadata>]
            [--file_path=<file_path>] [--fee=<fee>] [--title=<title>]
            [--description=<description>] [--author=<author>] [--language=<language>]
            [--license=<license>] [--license_url=<license_url>] [--thumbnail=<thumbnail>]
            [--preview=<preview>] [--nsfw=<nsfw>] [--sources=<sources>]
            [--channel_name=<channel_name>] [--channel_id=<channel_id>]
            [--claim_address=<claim_address>] [--change_address=<change_address>]

Options:
    --metadata=<metadata>          : ClaimDict to associate with the claim.
    --file_path=<file_path>        : path to file to be associated with name. If provided,
                                     a lbry stream of this file will be used in 'sources'.
                                     If no path is given but a metadata dict is provided,
                                     the source from the given metadata will be used.
    --fee=<fee>                    : Dictionary representing key fee to download content:
                                      {
                                        'currency': currency_symbol,
                                        'amount': float,
                                        'address': str, optional
                                      }
                                      supported currencies: LBC, USD, BTC
                                      If an address is not provided a new one will be
                                      automatically generated. Default fee is zero.
    --title=<title>                : title of the publication
    --description=<description>    : description of the publication
    --author=<author>              : author of the publication
    --language=<language>          : language of the publication
    --license=<license>            : publication license
    --license_url=<license_url>    : publication license url
    --thumbnail=<thumbnail>        : thumbnail url
    --preview=<preview>            : preview url
    --nsfw=<nsfw>                  : title of the publication
    --sources=<sources>            : {'lbry_sd_hash':sd_hash} specifies sd hash of file
    --channel_name=<channel_name>  : name of the publisher channel name in the wallet
    --channel_id=<channel_id>      : claim id of the publisher channel, does not check
                                     for channel claim being in the wallet. This allows
                                     publishing to a channel where only the certificate
                                     private key is in the wallet.
   --claim_address=<claim_address> : address where the claim is sent to, if not specified
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

## report_bug

```text
Report a bug to slack

Usage:
    report_bug (<message> | --message=<message>)

Returns:
    (bool) true if successful
```

## resolve

```text
Resolve given LBRY URIs

Usage:
    resolve [-f] (<uri> | --uri=<uri>) [<uris>...]

Options:
    -f  : force refresh and ignore cache

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
                'supports: (list) list of supports [{'txid': txid,
                                                     'nout': nout,
                                                     'amount': amount}],
                'txid': (str) claim txid,
                'nout': (str) claim nout,
                'signature_is_valid': (bool), included if has_signature,
                'value': ClaimDict if decoded, otherwise hex string
            }

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
                'channel_name': (str) channel name if claim is in a channel
                'supports: (list) list of supports [{'txid': txid,
                                                     'nout': nout,
                                                     'amount': amount}]
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

Usage:
    resolve_name <name> [-f]

Options:
    -f  : force refresh and do not check cache

Returns:
    (dict) Metadata dictionary from name claim, None if the name is not
            resolvable
```

## settings_get

```text
Get daemon settings

Usage:
    settings_get

Returns:
    (dict) Dictionary of daemon settings
    See ADJUSTABLE_SETTINGS in lbrynet/conf.py for full list of settings
```

## settings_set

```text
Set daemon settings

Usage:
    settings_set [<download_directory> | --download_directory=<download_directory>]
                 [<data_rate> | --data_rate=<data_rate>]
                 [<download_timeout> | --download_timeout=<download_timeout>]
                 [<peer_port> | --peer_port=<peer_port>]
                 [<max_key_fee> | --max_key_fee=<max_key_fee>]
                 [<disable_max_key_fee> | --disable_max_key_fee=<disable_max_key_fee>]
                 [<use_upnp> | --use_upnp=<use_upnp>]
                 [<run_reflector_server> | --run_reflector_server=<run_reflector_server>]
                 [<cache_time> | --cache_time=<cache_time>]
                 [<reflect_uploads> | --reflect_uploads=<reflect_uploads>]
                 [<share_usage_data> | --share_usage_data=<share_usage_data>]
                 [<peer_search_timeout> | --peer_search_timeout=<peer_search_timeout>]
                 [<sd_download_timeout> | --sd_download_timeout=<sd_download_timeout>]

Options:
    <download_directory>, --download_directory=<download_directory>  : (str)
    <data_rate>, --data_rate=<data_rate>                             : (float), 0.0001
    <download_timeout>, --download_timeout=<download_timeout>        : (int), 180
    <peer_port>, --peer_port=<peer_port>                             : (int), 3333
    <max_key_fee>, --max_key_fee=<max_key_fee>   : (dict) maximum key fee for downloads,
                                                    in the format: {
                                                        "currency": <currency_symbol>,
                                                        "amount": <amount>
                                                    }. In the CLI, it must be an escaped
                                                    JSON string
                                                    Supported currency symbols:
                                                        LBC
                                                        BTC
                                                        USD
    <disable_max_key_fee>, --disable_max_key_fee=<disable_max_key_fee> : (bool), False
    <use_upnp>, --use_upnp=<use_upnp>            : (bool), True
    <run_reflector_server>, --run_reflector_server=<run_reflector_server>  : (bool), False
    <cache_time>, --cache_time=<cache_time>  : (int), 150
    <reflect_uploads>, --reflect_uploads=<reflect_uploads>  : (bool), True
    <share_usage_data>, --share_usage_data=<share_usage_data>  : (bool), True
    <peer_search_timeout>, --peer_search_timeout=<peer_search_timeout>  : (int), 3
    <sd_download_timeout>, --sd_download_timeout=<sd_download_timeout>  : (int), 3

Returns:
    (dict) Updated dictionary of daemon settings
```

## status

```text
Get daemon status

Usage:
    status [-s] [-d]

Options:
    -s  : include session status in results
    -d  : include dht network and peer status

Returns:
    (dict) lbrynet-daemon status
    {
        'lbry_id': lbry peer id, base58
        'installation_id': installation id, base58
        'is_running': bool
        'is_first_run': bool
        'startup_status': {
            'code': status code
            'message': status message
        },
        'connection_status': {
            'code': connection status code
            'message': connection status message
        },
        'blockchain_status': {
            'blocks': local blockchain height,
            'blocks_behind': remote_height - local_height,
            'best_blockhash': block hash of most recent block,
        },

        If given the session status option:
            'session_status': {
                'managed_blobs': count of blobs in the blob manager,
                'managed_streams': count of streams in the file manager
            }

        If given the dht status option:
            'dht_status': {
                'kbps_received': current kbps receiving,
                'kbps_sent': current kdps being sent,
                'total_bytes_sent': total bytes sent
                'total_bytes_received': total bytes received
                'queries_received': number of queries received per second
                'queries_sent': number of queries sent per second
                'recent_contacts': count of recently contacted peers
                'unique_contacts': count of unique peers
            }
    }
```

## stream_cost_estimate

```text
Get estimated cost for a lbry stream

Usage:
    stream_cost_estimate <uri> [<size> | --size=<size>]

Options:
    <size>, --size=<size>  : stream size in bytes. if provided an sd blob won't be
                             downloaded.

Returns:
    (float) Estimated cost in lbry credits, returns None if uri is not
        resolveable
```

## transaction_list

```text
List transactions belonging to wallet

Usage:
    transaction_list

Returns:
    (list) List of transactions
```

## transaction_show

```text
Get a decoded transaction from a txid

Usage:
    transaction_show (<txid> | --txid=<txid>)

Returns:
    (dict) JSON formatted transaction
```

## version

```text
Get lbry version information

Usage:
    version

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

Usage:
    wallet_balance [<address> | --address=<address>] [-u]

Options:
    <address>  :  If provided only the balance for this address will be given
    -u         :  Include unconfirmed

Returns:
    (float) amount of lbry credits in wallet
```

## wallet_is_address_mine

```text
Checks if an address is associated with the current wallet.

Usage:
    wallet_is_address_mine (<address> | --address=<address>)

Returns:
    (bool) true, if address is associated with current wallet
```

## wallet_list

```text
List wallet addresses

Usage:
    wallet_list

Returns:
    List of wallet addresses
```

## wallet_new_address

```text
Generate a new wallet address

Usage:
    wallet_new_address

Returns:
    (str) New wallet address in base58
```

## wallet_public_key

```text
Get public key from wallet address

Usage:
    wallet_public_key (<address> | --address=<address>)

Returns:
    (list) list of public keys associated with address.
        Could contain more than one public key if multisig.
```

## wallet_send

```text
Send credits. If given an address, send credits to it. If given a claim id, send a tip
to the owner of a claim specified by uri. A tip is a claim support where the recipient
of the support is the claim address for the claim being supported.

Usage:
    wallet_send (<amount> | --amount=<amount>)
                ((<address> | --address=<address>) | (<claim_id> | --claim_id=<claim_id>))

Return:
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

## wallet_unused_address

```text
Return an address containing no balance, will create
a new address if there is none.

Usage:
    wallet_unused_address

Returns:
    (str) Unused wallet address in base58
```

