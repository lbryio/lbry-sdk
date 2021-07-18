#!/usr/bin/env python3
"""
Basic class with channel methods for the Daemon class (JSON-RPC server).
"""
import base58
import ecdsa
import hashlib
import json
from binascii import unhexlify

from lbry.extras.daemon import comment_client
from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires, deprecated
from lbry.extras.daemon.components import WALLET_COMPONENT
from lbry.wallet import Account, Input, Transaction
from lbry.wallet.dewies import dewies_to_lbc
from lbry.schema.claim import Claim


class Daemon_channel(metaclass=JSONRPCServerType):
    @deprecated('channel_create')
    def jsonrpc_channel_new(self):
        """ deprecated """

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_create(
            self, name, bid, allow_duplicate_name=False, account_id=None, wallet_id=None,
            claim_address=None, funding_account_ids=None, preview=False, blocking=False, **kwargs):
        """
        Create a new channel by generating a channel private key and establishing an '@' prefixed claim.

        Usage:
            channel_create (<name> | --name=<name>) (<bid> | --bid=<bid>)
                           [--allow_duplicate_name=<allow_duplicate_name>]
                           [--title=<title>] [--description=<description>] [--email=<email>]
                           [--website_url=<website_url>] [--featured=<featured>...]
                           [--tags=<tags>...] [--languages=<languages>...] [--locations=<locations>...]
                           [--thumbnail_url=<thumbnail_url>] [--cover_url=<cover_url>]
                           [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                           [--claim_address=<claim_address>] [--funding_account_ids=<funding_account_ids>...]
                           [--preview] [--blocking]

        Options:
            --name=<name>                  : (str) name of the channel prefixed with '@'
            --bid=<bid>                    : (decimal) amount to back the claim
        --allow_duplicate_name=<allow_duplicate_name> : (bool) create new channel even if one already exists with
                                              given name. default: false.
            --title=<title>                : (str) title of the publication
            --description=<description>    : (str) description of the publication
            --email=<email>                : (str) email of channel owner
            --website_url=<website_url>    : (str) website url
            --featured=<featured>          : (list) claim_ids of featured content in channel
            --tags=<tags>                  : (list) content tags
            --languages=<languages>        : (list) languages used by the channel,
                                                    using RFC 5646 format, eg:
                                                    for English `--languages=en`
                                                    for Spanish (Spain) `--languages=es-ES`
                                                    for Spanish (Mexican) `--languages=es-MX`
                                                    for Chinese (Simplified) `--languages=zh-Hans`
                                                    for Chinese (Traditional) `--languages=zh-Hant`
            --locations=<locations>        : (list) locations of the channel, consisting of 2 letter
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
            --cover_url=<cover_url>        : (str) url of cover image
            --account_id=<account_id>      : (str) account to use for holding the transaction
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
          --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --claim_address=<claim_address>: (str) address where the channel is sent to, if not specified
                                                   it will be determined automatically from the account
            --preview                      : (bool) do not broadcast the transaction
            --blocking                     : (bool) wait until transaction is in mempool

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        account = wallet.get_account_or_default(account_id)
        funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
        self.valid_channel_name_or_error(name)
        amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        claim_address = await self.get_receiving_address(claim_address, account)

        existing_channels = await self.ledger.get_channels(accounts=wallet.accounts, claim_name=name)
        if len(existing_channels) > 0:
            if not allow_duplicate_name:
                raise Exception(
                    f"You already have a channel under the name '{name}'. "
                    f"Use --allow-duplicate-name flag to override."
                )

        claim = Claim()
        claim.channel.update(**kwargs)
        tx = await Transaction.claim_create(
            name, claim, amount, claim_address, funding_accounts, funding_accounts[0]
        )
        txo = tx.outputs[0]
        await txo.generate_channel_private_key()

        await tx.sign(funding_accounts)

        if not preview:
            account.add_channel_private_key(txo.private_key)
            wallet.save()
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.storage.save_claims([self._old_get_temp_claim_info(
                tx, txo, claim_address, claim, name, dewies_to_lbc(amount)
            )]))
            self.component_manager.loop.create_task(self.analytics_manager.send_new_channel())
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_update(
            self, claim_id, bid=None, account_id=None, wallet_id=None, claim_address=None,
            funding_account_ids=None, new_signing_key=False, preview=False,
            blocking=False, replace=False, **kwargs):
        """
        Update an existing channel claim.

        Usage:
            channel_update (<claim_id> | --claim_id=<claim_id>) [<bid> | --bid=<bid>]
                           [--title=<title>] [--description=<description>] [--email=<email>]
                           [--website_url=<website_url>]
                           [--featured=<featured>...] [--clear_featured]
                           [--tags=<tags>...] [--clear_tags]
                           [--languages=<languages>...] [--clear_languages]
                           [--locations=<locations>...] [--clear_locations]
                           [--thumbnail_url=<thumbnail_url>] [--cover_url=<cover_url>]
                           [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                           [--claim_address=<claim_address>] [--new_signing_key]
                           [--funding_account_ids=<funding_account_ids>...]
                           [--preview] [--blocking] [--replace]

        Options:
            --claim_id=<claim_id>          : (str) claim_id of the channel to update
            --bid=<bid>                    : (decimal) amount to back the claim
            --title=<title>                : (str) title of the publication
            --description=<description>    : (str) description of the publication
            --email=<email>                : (str) email of channel owner
            --website_url=<website_url>    : (str) website url
            --featured=<featured>          : (list) claim_ids of featured content in channel
            --clear_featured               : (bool) clear existing featured content (prior to adding new ones)
            --tags=<tags>                  : (list) add content tags
            --clear_tags                   : (bool) clear existing tags (prior to adding new ones)
            --languages=<languages>        : (list) languages used by the channel,
                                                    using RFC 5646 format, eg:
                                                    for English `--languages=en`
                                                    for Spanish (Spain) `--languages=es-ES`
                                                    for Spanish (Mexican) `--languages=es-MX`
                                                    for Chinese (Simplified) `--languages=zh-Hans`
                                                    for Chinese (Traditional) `--languages=zh-Hant`
            --clear_languages              : (bool) clear existing languages (prior to adding new ones)
            --locations=<locations>        : (list) locations of the channel, consisting of 2 letter
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
            --cover_url=<cover_url>        : (str) url of cover image
            --account_id=<account_id>      : (str) account in which to look for channel (default: all)
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
          --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --claim_address=<claim_address>: (str) address where the channel is sent
            --new_signing_key              : (bool) generate a new signing key, will invalidate all previous publishes
            --preview                      : (bool) do not broadcast the transaction
            --blocking                     : (bool) wait until transaction is in mempool
            --replace                      : (bool) instead of modifying specific values on
                                                    the channel, this will clear all existing values
                                                    and only save passed in values, useful for form
                                                    submissions where all values are always set

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
        if account_id:
            account = wallet.get_account_or_error(account_id)
            accounts = [account]
        else:
            account = wallet.default_account
            accounts = wallet.accounts

        existing_channels = await self.ledger.get_claims(
            wallet=wallet, accounts=accounts, claim_id=claim_id
        )
        if len(existing_channels) != 1:
            account_ids = ', '.join(f"'{account.id}'" for account in accounts)
            raise Exception(
                f"Can't find the channel '{claim_id}' in account(s) {account_ids}."
            )
        old_txo = existing_channels[0]
        if not old_txo.claim.is_channel:
            raise Exception(
                f"A claim with id '{claim_id}' was found but it is not a channel."
            )

        if bid is not None:
            amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        else:
            amount = old_txo.amount

        if claim_address is not None:
            self.valid_address_or_error(claim_address)
        else:
            claim_address = old_txo.get_address(account.ledger)

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
            await new_txo.generate_channel_private_key()
        else:
            new_txo.private_key = old_txo.private_key

        new_txo.script.generate()

        await tx.sign(funding_accounts)

        if not preview:
            account.add_channel_private_key(new_txo.private_key)
            wallet.save()
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.storage.save_claims([self._old_get_temp_claim_info(
                tx, new_txo, claim_address, new_txo.claim, new_txo.claim_name, dewies_to_lbc(amount)
            )]))
            self.component_manager.loop.create_task(self.analytics_manager.send_new_channel())
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_sign(
            self, channel_name=None, channel_id=None, hexdata=None, channel_account_id=None, wallet_id=None):
        """
        Signs data using the specified channel signing key.

        Usage:
            channel_sign [<channel_name> | --channel_name=<channel_name>]
                         [<channel_id> | --channel_id=<channel_id>] [<hexdata> | --hexdata=<hexdata>]
                         [--channel_account_id=<channel_account_id>...] [--wallet_id=<wallet_id>]

        Options:
            --channel_name=<channel_name>            : (str) name of channel used to sign (or use channel id)
            --channel_id=<channel_id>                : (str) claim id of channel used to sign (or use channel name)
            --hexdata=<hexdata>                      : (str) data to sign, encoded as hexadecimal
            --channel_account_id=<channel_account_id>: (str) one or more account ids for accounts to look in
                                                             for channel certificates, defaults to all accounts.
            --wallet_id=<wallet_id>                  : (str) restrict operation to specific wallet

        Returns:
            (dict) Signature if successfully made, (None) or an error otherwise
            {
                "signature":    (str) The signature of the comment,
                "signing_ts":   (str) The timestamp used to sign the comment,
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        signing_channel = await self.get_channel_or_error(
            wallet, channel_account_id, channel_id, channel_name, for_signing=True
        )
        return comment_client.sign(signing_channel, unhexlify(hexdata))

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_abandon(
            self, claim_id=None, txid=None, nout=None, account_id=None, wallet_id=None,
            preview=False, blocking=True):
        """
        Abandon one of my channel claims.

        Usage:
            channel_abandon [<claim_id> | --claim_id=<claim_id>]
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
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
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
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('abandon'))
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    def jsonrpc_channel_list(self, *args, **kwargs):
        """
        List my channel claims.

        Usage:
            channel_list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]
                         [--name=<name>...] [--claim_id=<claim_id>...] [--is_spent]
                         [--page=<page>] [--page_size=<page_size>] [--resolve] [--no_totals]

        Options:
            --name=<name>              : (str or list) channel name
            --claim_id=<claim_id>      : (str or list) channel id
            --is_spent                 : (bool) shows previous channel updates and abandons
            --account_id=<account_id>  : (str) id of the account to use
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination
            --resolve                  : (bool) resolves each channel to provide additional metadata
            --no_totals                : (bool) do not calculate the total number of pages and items in result set
                                                (significant performance boost)

        Returns: {Paginated[Output]}
        """
        kwargs['type'] = 'channel'
        if 'is_spent' not in kwargs or not kwargs['is_spent']:
            kwargs['is_not_spent'] = True
        return self.jsonrpc_txo_list(*args, **kwargs)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_export(self, channel_id=None, channel_name=None, account_id=None, wallet_id=None):
        """
        Export channel private key.

        Usage:
            channel_export (<channel_id> | --channel_id=<channel_id> | --channel_name=<channel_name>)
                           [--account_id=<account_id>...] [--wallet_id=<wallet_id>]

        Options:
            --channel_id=<channel_id>     : (str) claim id of channel to export
            --channel_name=<channel_name> : (str) name of channel to export
            --account_id=<account_id>     : (str) one or more account ids for accounts
                                                  to look in for channels, defaults to
                                                  all accounts.
            --wallet_id=<wallet_id>       : (str) restrict operation to specific wallet

        Returns:
            (str) serialized channel private key
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        channel = await self.get_channel_or_error(wallet, account_id, channel_id, channel_name, for_signing=True)
        address = channel.get_address(self.ledger)
        public_key = await self.ledger.get_public_key_for_address(wallet, address)
        if not public_key:
            raise Exception("Can't find public key for address holding the channel.")
        export = {
            'name': channel.claim_name,
            'channel_id': channel.claim_id,
            'holding_address': address,
            'holding_public_key': public_key.extended_key_string(),
            'signing_private_key': channel.private_key.to_pem().decode()
        }
        return base58.b58encode(json.dumps(export, separators=(',', ':')))

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_import(self, channel_data, wallet_id=None):
        """
        Import serialized channel private key (to allow signing new streams to the channel)

        Usage:
            channel_import (<channel_data> | --channel_data=<channel_data>) [--wallet_id=<wallet_id>]

        Options:
            --channel_data=<channel_data> : (str) serialized channel, as exported by channel export
            --wallet_id=<wallet_id>       : (str) import into specific wallet

        Returns:
            (dict) Result dictionary
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)

        decoded = base58.b58decode(channel_data)
        data = json.loads(decoded)
        channel_private_key = ecdsa.SigningKey.from_pem(
            data['signing_private_key'], hashfunc=hashlib.sha256
        )
        public_key_der = channel_private_key.get_verifying_key().to_der()

        # check that the holding_address hasn't changed since the export was made
        holding_address = data['holding_address']
        channels, _, _, _ = await self.ledger.claim_search(
            wallet.accounts, public_key_id=self.ledger.public_key_to_address(public_key_der)
        )
        if channels and channels[0].get_address(self.ledger) != holding_address:
            holding_address = channels[0].get_address(self.ledger)

        account = await self.ledger.get_account_for_address(wallet, holding_address)
        if account:
            # Case 1: channel holding address is in one of the accounts we already have
            #         simply add the certificate to existing account
            pass
        else:
            # Case 2: channel holding address hasn't changed and thus is in the bundled read-only account
            #         create a single-address holding account to manage the channel
            if holding_address == data['holding_address']:
                account = Account.from_dict(self.ledger, wallet, {
                    'name': f"Holding Account For Channel {data['name']}",
                    'public_key': data['holding_public_key'],
                    'address_generator': {'name': 'single-address'}
                })
                if self.ledger.network.is_connected:
                    await self.ledger.subscribe_account(account)
                    await self.ledger._update_tasks.done.wait()
            # Case 3: the holding address has changed and we can't create or find an account for it
            else:
                raise Exception(
                    "Channel owning account has changed since the channel was exported and "
                    "it is not an account to which you have access."
                )
        account.add_channel_private_key(channel_private_key)
        wallet.save()
        return f"Added channel signing key for {data['name']}."
