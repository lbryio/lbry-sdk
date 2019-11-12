@requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
async def jsonrpc_collection_create(
        self, name, bid, allow_duplicate_name=False,
        channel_id=None, channel_name=None, channel_account_id=None,
        account_id=None, wallet_id=None, claim_address=None, funding_account_ids=None,
        preview=False, blocking=False, **kwargs):
    """
    Create a new collection ....

    Usage:
        collection_create (<name> | --name=<name>) (<bid> | --bid=<bid>)
                       [--allow_duplicate_name=<allow_duplicate_name>]
                       [--title=<title>] [--description=<description>]
                       [--tags=<tags>...] [--languages=<languages>...] [--locations=<locations>...]
                       [--thumbnail_url=<thumbnail_url>]
                       [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                       [--claim_address=<claim_address>] [--funding_account_ids=<funding_account_ids>...]
                       [--preview] [--blocking]

    Options:
        --name=<name>                  : (str) name of the collection
        --bid=<bid>                    : (decimal) amount to back the claim
    --allow_duplicate_name=<allow_duplicate_name> : (bool) create new collection even if one already exists with
                                          given name. default: false.
        --claims=<claims>              : (list) claim ids
        --title=<title>                : (str) title of the publication
        --description=<description>    : (str) description of the publication
        --tags=<tags>                  : (list) content tags
        --languages=<languages>        : (list) languages used by the collection,
                                                using RFC 5646 format, eg:
                                                for English `--languages=en`
                                                for Spanish (Spain) `--languages=es-ES`
                                                for Spanish (Mexican) `--languages=es-MX`
                                                for Chinese (Simplified) `--languages=zh-Hans`
                                                for Chinese (Traditional) `--languages=zh-Hant`
        --locations=<locations>        : (list) locations of the collection, consisting of 2 letter
                                                `country` code and a `state`, `city` and a postal
                                                `code` along with a `latitude` and `longitude`.
                                                for JSON RPC: pass a dictionary with aforementioned
                                                    attributes as keys, eg:
                                                    ...
                                                    "locations": [{'country': 'US', 'state': 'NH'}]
                                                    ...
                                                for command line: pass a colon delimited list
                                                    with values in the following order:

                                                      "COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE"

                                                    making sure to include colon for blank values, for
                                                    example to provide only the city:

                                                      ... --locations="::Manchester"

                                                    with all values set:

                                             ... --locations="US:NH:Manchester:03101:42.990605:-71.460989"

                                                    optionally, you can just pass the "LATITUDE:LONGITUDE":

                                                      ... --locations="42.990605:-71.460989"

                                                    finally, you can also pass JSON string of dictionary
                                                    on the command line as you would via JSON RPC

                                                      ... --locations="{'country': 'US', 'state': 'NH'}"

        --thumbnail_url=<thumbnail_url>: (str) thumbnail url
        # --cover_url=<cover_url>        : (str) url of cover image
        --account_id=<account_id>      : (str) account to use for holding the transaction
        --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
        --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
        --claim_address=<claim_address>: (str) address where the collection is sent to, if not specified
                                               it will be determined automatically from the account
        --preview                      : (bool) do not broadcast the transaction
        --blocking                     : (bool) wait until transaction is in mempool

    Returns: {Transaction}
    """
    wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
    account = wallet.get_account_or_default(account_id)
    funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
    self.valid_collection_name_or_error(name)
    channel = await self.get_channel_or_none(wallet, channel_account_id, channel_id, channel_name, for_signing=True)
    amount = self.get_dewies_or_error('bid', bid, positive_value=True)
    claim_address = await self.get_receiving_address(claim_address, account)
    kwargs['fee_address'] = self.get_fee_address(kwargs, claim_address)

    existing_collections = await self.ledger.get_collections(accounts=wallet.accounts, claim_name=name)
    if len(existing_collections) > 0:
        if not allow_duplicate_name:
            raise Exception(
                f"You already have a collection under the name '{name}'. "
                f"Use --allow-duplicate-name flag to override."
            )

    claim = Claim()
    claim.collection.update(**kwargs) #maybe specify claims=[]
    tx = await Transaction.claim_create(
        name, claim, amount, claim_address, funding_accounts, funding_accounts[0], channel
    )
    new_txo = tx.outputs[0]

    if channel:
        new_txo.sign(channel)
    await tx.sign(funding_accounts)
    if not preview:
        await self.broadcast_or_release(tx, blocking)
        await self.storage.save_claims([self._old_get_temp_claim_info(
            tx, new_txo, claim_address, claim, name, dewies_to_lbc(amount)
        )])
        # await self.analytics_manager.send_new_channel()
    else:
        await account.ledger.release_tx(tx)

    return tx

@requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
async def jsonrpc_collection_update(
        self, claim_id, bid=None, claim=None, allow_duplicate_name=False,
        channel_id=None, channel_name=None, channel_account_id=None, clear_channel=False,
        account_id=None, wallet_id=None, claim_address=None, funding_account_ids=None,
        preview=False, blocking=False, replace=False, **kwargs):
    """
    Update an existing collection claim.

    Usage:
        collection_update (<claim_id> | --claim_id=<claim_id>) [<bid> | --bid=<bid>]
                       [--title=<title>] [--description=<description>]
                       [--tags=<tags>...] [--clear_tags]
                       [--languages=<languages>...] [--clear_languages]
                       [--locations=<locations>...] [--clear_locations]
                       [--thumbnail_url=<thumbnail_url>] [--cover_url=<cover_url>]
                       [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                       [--claim_address=<claim_address>] [--new_signing_key]
                       [--funding_account_ids=<funding_account_ids>...]
                       [--preview] [--blocking] [--replace]

    Options:
        --claim_id=<claim_id>          : (str) claim_id of the collection to update
        --bid=<bid>                    : (decimal) amount to back the claim
        --title=<title>                : (str) title of the publication
        --description=<description>    : (str) description of the publication
        --tags=<tags>                  : (list) add content tags
        --clear_tags                   : (bool) clear existing tags (prior to adding new ones)
        --languages=<languages>        : (list) languages used by the collection,
                                                using RFC 5646 format, eg:
                                                for English `--languages=en`
                                                for Spanish (Spain) `--languages=es-ES`
                                                for Spanish (Mexican) `--languages=es-MX`
                                                for Chinese (Simplified) `--languages=zh-Hans`
                                                for Chinese (Traditional) `--languages=zh-Hant`
        --clear_languages              : (bool) clear existing languages (prior to adding new ones)
        --locations=<locations>        : (list) locations of the collection, consisting of 2 letter
                                                `country` code and a `state`, `city` and a postal
                                                `code` along with a `latitude` and `longitude`.
                                                for JSON RPC: pass a dictionary with aforementioned
                                                    attributes as keys, eg:
                                                    ...
                                                    "locations": [{'country': 'US', 'state': 'NH'}]
                                                    ...
                                                for command line: pass a colon delimited list
                                                    with values in the following order:

                                                      "COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE"

                                                    making sure to include colon for blank values, for
                                                    example to provide only the city:

                                                      ... --locations="::Manchester"

                                                    with all values set:

                                             ... --locations="US:NH:Manchester:03101:42.990605:-71.460989"

                                                    optionally, you can just pass the "LATITUDE:LONGITUDE":

                                                      ... --locations="42.990605:-71.460989"

                                                    finally, you can also pass JSON string of dictionary
                                                    on the command line as you would via JSON RPC

                                                      ... --locations="{'country': 'US', 'state': 'NH'}"

        --clear_locations              : (bool) clear existing locations (prior to adding new ones)
        --thumbnail_url=<thumbnail_url>: (str) thumbnail url
        #--cover_url=<cover_url>        : (str) url of cover image
        --account_id=<account_id>      : (str) account in which to look for collection (default: all)
        --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
      --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
        --claim_address=<claim_address>: (str) address where the collection is sent
        --new_signing_key              : (bool) generate a new signing key, will invalidate all previous publishes
        --preview                      : (bool) do not broadcast the transaction
        --blocking                     : (bool) wait until transaction is in mempool
        --replace                      : (bool) instead of modifying specific values on
                                                the collection, this will clear all existing values
                                                and only save passed in values, useful for form
                                                submissions where all values are always set

    Returns: {Transaction}
    """
    wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
    funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
    if account_id:
        account = wallet.get_account_or_error(account_id)
        accounts = [account]
    else:
        account = wallet.default_account
        accounts = wallet.accounts

    existing_collections = await self.ledger.get_collections(
        wallet=wallet, accounts=accounts, claim_id=claim_id
    )
    if len(existing_collections) != 1:
        account_ids = ', '.join(f"'{account.id}'" for account in accounts)
        raise Exception(
            f"Can't find the collection '{claim_id}' in account(s) {account_ids}."
        )
    # Here we might have a problem of replacing a stream with a collection
    old_txo = existing_collections[0]
    if not old_txo.claim.is_collection: #as we're only checking @ or not, this is not definitive
        raise Exception(
            f"A claim with id '{claim_id}' was found but it is not a stream or collection."
        )

    if bid is not None:
        amount = self.get_dewies_or_error('bid', bid, positive_value=True)
    else:
        amount = old_txo.amount

    if claim_address is not None:
        self.valid_address_or_error(claim_address)
    else:
        claim_address = old_txo.get_address(account.ledger)

    channel = None
    if channel_id or channel_name:
        channel = await self.get_channel_or_error(
            wallet, channel_account_id, channel_id, channel_name, for_signing=True)
    elif old_txo.claim.is_signed and not clear_channel and not replace:
        channel = old_txo.channel

    fee_address = self.get_fee_address(kwargs, claim_address)
    if fee_address:
        kwargs['fee_address'] = fee_address

    if replace:
        claim = Claim()
        claim.channel.public_key_bytes = old_txo.claim.channel.public_key_bytes
    else:
        claim = Claim.from_bytes(old_txo.claim.to_bytes())
    claim.channel.update(**kwargs)
    tx = await Transaction.claim_update(
        old_txo, claim, amount, claim_address, funding_accounts, funding_accounts[0]
    )
    new_txo = tx.outputs[0]

    if new_signing_key:
        new_txo.generate_channel_private_key()
    else:
        new_txo.private_key = old_txo.private_key

    new_txo.script.generate()

    if not preview:
        await tx.sign(funding_accounts)
        account.add_channel_private_key(new_txo.private_key)
        wallet.save()
        await self.broadcast_or_release(tx, blocking)
        await self.storage.save_claims([self._old_get_temp_claim_info(
            tx, new_txo, claim_address, new_txo.claim, new_txo.claim_name, dewies_to_lbc(amount)
        )])
        await self.analytics_manager.send_new_channel()
    else:
        await account.ledger.release_tx(tx)

    return tx

@requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
async def jsonrpc_collection_abandon(
        self, claim_id=None, txid=None, nout=None, account_id=None, wallet_id=None,
        preview=False, blocking=True):
    """
    Abandon one of my collection claims.

    Usage:
        collection_abandon [<claim_id> | --claim_id=<claim_id>]
                        [<txid> | --txid=<txid>] [<nout> | --nout=<nout>]
                        [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                        [--preview] [--blocking]

    Options:
        --claim_id=<claim_id>     : (str) claim_id of the claim to abandon
        --txid=<txid>             : (str) txid of the claim to abandon
        --nout=<nout>             : (int) nout of the claim to abandon
        --account_id=<account_id> : (str) id of the account to use
        --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet
        --preview                 : (bool) do not broadcast the transaction
        --blocking                : (bool) wait until abandon is in mempool

    Returns: {Transaction}
    """
    wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
    if account_id:
        account = wallet.get_account_or_error(account_id)
        accounts = [account]
    else:
        account = wallet.default_account
        accounts = wallet.accounts

    if txid is not None and nout is not None:
        claims = await self.ledger.get_claims(
            wallet=wallet, accounts=accounts, **{'txo.txid': txid, 'txo.position': nout}
        )
    elif claim_id is not None:
        claims = await self.ledger.get_claims(
            wallet=wallet, accounts=accounts, claim_id=claim_id
        )
    else:
        raise Exception('Must specify claim_id, or txid and nout')

    if not claims:
        raise Exception('No claim found for the specified claim_id or txid:nout')

    tx = await Transaction.create(
        [Input.spend(txo) for txo in claims], [], [account], account
    )

    if not preview:
        await self.broadcast_or_release(tx, blocking)
        await self.analytics_manager.send_claim_action('abandon')
    else:
        await account.ledger.release_tx(tx)

    return tx

@requires(WALLET_COMPONENT)
def jsonrpc_collection_list(self, account_id=None, wallet_id=None, page=None, page_size=None):
    """
    List my collection claims.

    Usage:
        collection_list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]
                     [--page=<page>] [--page_size=<page_size>]

    Options:
        --account_id=<account_id>  : (str) id of the account to use
        --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
        --page=<page>              : (int) page to return during paginating
        --page_size=<page_size>    : (int) number of items on page during pagination

    Returns: {Paginated[Output]}
    """
    wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
    if account_id:
        account: LBCAccount = wallet.get_account_or_error(account_id)
        collections = account.get_collections
        collection_count = account.get_collection_count
    else:
        collections = partial(self.ledger.get_collections, wallet=wallet, accounts=wallet.accounts)
        collection_count = partial(self.ledger.get_collection_count, wallet=wallet, accounts=wallet.accounts)
    return maybe_paginate(collections, collection_count, page, page_size)
