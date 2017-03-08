# LBRY JSON-RPC API Documentation

## blob_announce_all

```text
Announce all blobs to the DHT

Args:
    None
Returns:
```

## blob_delete

```text
Delete a blob

Args:
    blob_hash
Returns:
    Success/fail message
```

## blob_get

```text
Download and return a blob

Args:
    blob_hash
    timeout (optional)
    encoding (optional): by default no attempt at decoding is made
                         can be set to one of the following decoders:
                         json
    payment_rate_manager (optional): if not given the default payment rate manager
                                     will be used. supported alternative rate managers:
                                     only-free

Returns
    Success/Fail message or decoded data
```

## blob_list

```text
Returns blob hashes, if not given filters returns all blobs known by the blob manager

Args:
    uri (str, optional): filter by blobs in stream for winning claim
    stream_hash (str, optional): filter by blobs in given stream hash
    sd_hash (str, optional): filter by blobs in given sd hash
    needed (bool, optional): only return needed blobs
    finished (bool, optional): only return finished blobs
    page_size (int, optional): limit number of results returned
    page (int, optional): filter to page x of [page_size] results
Returns:
    list of blob hashes
```

## blob_reflect_all

```text
Reflects all saved blobs

Args:
    None
Returns:
    True
```

## block_show

```text
Get contents of a block

Args:
    blockhash: hash of the block to look up
Returns:
    requested block
```

## claim_abandon

```text
Abandon a name and reclaim credits from the claim

Args:
    'txid': txid of claim, string
    'nout': nout of claim, integer
Return:
    txid : txid of resulting transaction if succesful
    fee : fee paid for the transaction if succesful
```

## claim_list

```text
Get claims for a name

Args:
    name: file name
    txid: transaction id of a name claim transaction
Returns
    list of name claims
```

## claim_list_mine

```text
List my name claims

Args:
    None
Returns
    list of name claims
```

## claim_new_support

```text
Support a name claim

Args:
    'name': name
    'claim_id': claim id of claim to support
    'amount': amount to support by
Return:
    txid : txid of resulting transaction if succesful
    nout : nout of the resulting support claim if succesful
    fee : fee paid for the transaction if succesful
```

## claim_show

```text
Resolve claim info from a LBRY uri

Args:
    'name': name to look up, string, do not include lbry:// prefix
    'txid': optional, if specified, look for claim with this txid
    'nout': optional, if specified, look for claim with this nout

Returns:
    txid, amount, value, n, height
```

## commands

```text
Return a list of available commands

Returns:
    list
```

## daemon_stop

```text
Stop lbrynet-daemon

Returns:
    shutdown message
```

## descriptor_get

```text
Download and return a sd blob

Args:
    sd_hash
    timeout (optional)
    payment_rate_manager (optional): if not given the default payment rate manager
                                     will be used. supported alternative rate managers:
                                     only-free

Returns
    Success/Fail message or decoded data
```

## file_delete

```text
Delete a lbry file

Args:
    'file_name': downloaded file name, string
Returns:
    confirmation message
```

## file_get

```text
Get a file, if no matching file exists returns False

Args:
    'name': get file by lbry uri,
    'sd_hash': get file by the hash in the name claim,
    'file_name': get file by its name in the downloads folder,
    'stream_hash': get file by its stream hash
Returns:
    'completed': bool,
    'file_name': str,
    'download_directory': str,
    'points_paid': float,
    'stopped': bool,
    'stream_hash': str (hex),
    'stream_name': str,
    'suggested_file_name': str,
    'sd_hash': str (hex),
    'lbry_uri': str,
    'txid': str (b58),
    'claim_id': str (b58),
    'download_path': str,
    'mime_type': str,
    'key': str (hex),
    'total_bytes': int,
    'written_bytes': int,
    'code': str,
    'message': str
    'metadata': Metadata dict if claim is valid, otherwise status str
}
```

## file_list

```text
List files

Args:
    None
Returns:
    List of files, with the following keys:
    'completed': bool
    'file_name': string
    'key': hex string
    'points_paid': float
    'stopped': bool
    'stream_hash': base 58 string
    'stream_name': string
    'suggested_file_name': string
    'sd_hash': string
```

## file_seed

```text
Start or stop seeding a file

Args:
    'status': "start" or "stop"
    'name': start file by lbry uri,
    'sd_hash': start file by the hash in the name claim,
    'file_name': start file by its name in the downloads folder,
Returns:
    confirmation message
```

## get

```text
Download stream from a LBRY uri.

Args:
    'name': name to download, string
    'file_name': optional, a user specified name for the downloaded file
    'stream_info': optional, specified stream info overrides name
    'timeout': optional
    'download_directory': optional, path to directory where file will be saved, string
    'wait_for_write': optional, defaults to True. When set, waits for the file to
        only start to be written before returning any results.
Returns:
    'stream_hash': hex string
    'path': path of download
```

## get_availability

```text
Get stream availability for a winning claim

Arg:
    name (str): lbry uri
    sd_timeout (int, optional): sd blob download timeout
    peer_timeout (int, optional): how long to look for peers

Returns:
     peers per blob / total blobs
```

## get_mean_availability

```text
Get mean blob availability

Args:
    None
Returns:
    Mean peers for a blob
```

## get_nametrie

```text
Get the nametrie

Args:
    None
Returns:
    Name claim trie
```

## help

```text
Return a useful message for an API command

Args:
    'command': optional, command to retrieve documentation for
Returns:
    if given a command, returns documentation about that command
    otherwise returns general help message
```

## open

```text
Instruct the OS to open a file with its default program.

Args:
    'sd_hash': SD hash of file to be opened
Returns:
    True, opens file
```

## peer_list

```text
Get peers for blob hash

Args:
    'blob_hash': blob hash
    'timeout' (int, optional): peer search timeout
Returns:
    List of contacts
```

## publish

```text
Make a new name claim and publish associated data to lbrynet

Args:
    'name': str, name to be claimed, string
    'bid': float, amount of credits to commit in this claim,
    'metadata': dict, Metadata compliant (can be missing sources if a file is provided)
    'file_path' (optional): str, path to file to be associated with name, if not given
                            the stream from your existing claim for the name will be used
    'fee' (optional): dict, FeeValidator compliant
Returns:
    'success' : True if claim was succesful , False otherwise
    'reason' : if not succesful, give reason
    'txid' : txid of resulting transaction if succesful
    'nout' : nout of the resulting support claim if succesful
    'fee' : fee paid for the claim transaction if succesful
    'claim_id' : claim id of the resulting transaction
```

## reflect

```text
Reflect a stream

Args:
    sd_hash: sd_hash of lbry file
Returns:
    True or traceback
```

## report_bug

```text
Report a bug to slack

Args:
    'message': string, message to send
Returns:
    True if successful
```

## resolve_name

```text
Resolve stream info from a LBRY uri

Args:
    'name': name to look up, string, do not include lbry:// prefix
Returns:
    metadata from name claim or None if the name is not known
```

## reveal

```text
Reveal a file or directory in file browser

Args:
    'path': path to be revealed in file browser
Returns:
    True, opens file browser
```

## send_amount_to_address

```text
Send credits to an address

Args:
    amount: the amount to send
    address: the address of the recipient
Returns:
    True if payment successfully scheduled
```

## settings_get

```text
Get daemon settings

Returns:
    'run_on_startup': bool,
    'data_rate': float,
    'max_key_fee': float,
    'download_directory': string,
    'max_upload': float, 0.0 for unlimited
    'max_download': float, 0.0 for unlimited
    'search_timeout': float,
    'download_timeout': int
    'max_search_results': int,
    'wallet_type': string,
    'delete_blobs_on_remove': bool,
    'peer_port': int,
    'dht_node_port': int,
    'use_upnp': bool,
```

## settings_set

```text
Set daemon settings

Args:
    'run_on_startup': bool,
    'data_rate': float,
    'max_key_fee': float,
    'download_directory': string,
    'max_upload': float, 0.0 for unlimited
    'max_download': float, 0.0 for unlimited
    'download_timeout': int
Returns:
    settings dict
```

## status

```text
Return daemon status

Args:
    session_status: bool
    blockchain_status: bool
Returns:
    daemon status
```

## stream_cost_estimate

```text
Get estimated cost for a lbry stream

Args:
    'name': lbry uri
    'size': stream size, in bytes. if provided an sd blob won't be downloaded.
Returns:
    estimated cost
```

## transaction_list

```text
List transactions

Args:
    None
Returns:
    list of transactions
```

## transaction_show

```text
Get a decoded transaction from a txid

Args:
    txid: txid hex string
Returns:
    JSON formatted transaction
```

## version

```text
Get lbry version information

Args:
    None
Returns:
    "platform": platform string
    "os_release": os release string
    "os_system": os name
    "lbrynet_version: ": lbrynet_version,
    "lbryum_version: ": lbryum_version,
    "ui_version": commit hash of ui version being used
    "remote_lbrynet": most recent lbrynet version available from github
    "remote_lbryum": most recent lbryum version available from github
```

## wallet_balance

```text
Return the balance of the wallet

Returns:
    balance, float
```

## wallet_is_address_mine

```text
Checks if an address is associated with the current wallet.

Args:
    address: string
Returns:
    is_mine: bool
```

## wallet_new_address

```text
Generate a new wallet address

Args:
    None
Returns:
    new wallet address, base 58 string
```

## wallet_public_key

```text
Get public key from wallet address

Args:
    wallet: wallet address, base58
Returns:
    public key
```

