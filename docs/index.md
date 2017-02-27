# LBRY JSON-RPC API Documentation

## abandon_name

```text
DEPRECIATED, use abandon_claim

Args:
    'txid': txid of claim, string
Return:
    txid
```

## blob_announce_all

```text
Announce all blobs to the DHT

Args:
    None
Returns:
```

## blob_get

```text
Download and return a sd blob

Args:
    sd_hash
Returns
    sd blob, dict
```

## blob_list

```text
Returns all blob hashes

Args:
    None
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

## configure_ui

```text
Configure the UI being hosted

Args, optional:
    'branch': a branch name on lbryio/lbry-web-ui
    'path': path to a ui folder
```

## daemon_stop

```text
Stop lbrynet-daemon

Returns:
    shutdown message
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
Get a file

Args:
    'name': get file by lbry uri,
    'sd_hash': get file by the hash in the name claim,
    'file_name': get file by its name in the downloads folder,
Returns:
    'completed': bool
    'file_name': string
    'key': hex string
    'points_paid': float
    'stopped': bool
    'stream_hash': base 58 string
    'stream_name': string
    'suggested_file_name': string
    'upload_allowed': bool
    'sd_hash': string
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
    'upload_allowed': bool
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
    'download_directory': optional, path to directory where file will be saved, string
    'file_name': optional, a user specified name for the downloaded file
    'stream_info': optional, specified stream info overrides name
    'timeout': optional
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

## peer_list

```text
Get peers for blob hash

Args:
    'blob_hash': blob hash
Returns:
    List of contacts
```

## publish

```text
Make a new name claim and publish associated data to lbrynet

Args:
    'name': name to be claimed, string
    'file_path': path to file to be associated with name, string
    'bid': amount of credits to commit in this claim, float
    'metadata': metadata dictionary
    optional 'fee'
Returns:
    'success' : True if claim was succesful , False otherwise
    'reason' : if not succesful, give reason
    'txid' : txid of resulting transaction if succesful
    'nout' : nout of the resulting support claim if succesful
    'fee' : fee paid for the claim transaction if succesful
    'claimid' : claimid of the resulting transaction
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
    metadata from name claim
```

## reveal

```text
Reveal a file or directory in file browser

Args:
    'path': path to be selected in file browser
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
Get lbrynet daemon settings

Args:
    None
Returns:
    'run_on_startup': bool,
    'data_rate': float,
    'max_key_fee': float,
    'download_directory': string,
    'max_upload': float, 0.0 for unlimited
    'max_download': float, 0.0 for unlimited
    'upload_log': bool,
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
Set lbrynet daemon settings

Args:
    'run_on_startup': bool,
    'data_rate': float,
    'max_key_fee': float,
    'download_directory': string,
    'max_upload': float, 0.0 for unlimited
    'max_download': float, 0.0 for unlimited
    'upload_log': bool,
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

