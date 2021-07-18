#!/usr/bin/env python3
"""
Basic class with stream methods for the Daemon class (JSON-RPC server).
"""
from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import VALID_FULL_CLAIM_ID
from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.components import (WALLET_COMPONENT,
                                           EXCHANGE_RATE_MANAGER_COMPONENT,
                                           DHT_COMPONENT,
                                           FILE_MANAGER_COMPONENT,
                                           BLOB_COMPONENT,
                                           DATABASE_COMPONENT)

from lbry.schema.claim import Claim
from lbry.wallet import Input, Transaction
from lbry.wallet.dewies import dewies_to_lbc


class Daemon_stream(metaclass=JSONRPCServerType):
    @requires(WALLET_COMPONENT, FILE_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT)
    async def jsonrpc_publish(self, name, **kwargs):
        """
        Create or replace a stream claim at a given name (use 'stream create/update' for more control).

        Usage:
            publish (<name> | --name=<name>) [--bid=<bid>] [--file_path=<file_path>]
                    [--file_name=<file_name>] [--file_hash=<file_hash>] [--validate_file] [--optimize_file]
                    [--fee_currency=<fee_currency>] [--fee_amount=<fee_amount>] [--fee_address=<fee_address>]
                    [--title=<title>] [--description=<description>] [--author=<author>]
                    [--tags=<tags>...] [--languages=<languages>...] [--locations=<locations>...]
                    [--license=<license>] [--license_url=<license_url>] [--thumbnail_url=<thumbnail_url>]
                    [--release_time=<release_time>] [--width=<width>] [--height=<height>] [--duration=<duration>]
                    [--sd_hash=<sd_hash>] [--channel_id=<channel_id> | --channel_name=<channel_name>]
                    [--channel_account_id=<channel_account_id>...]
                    [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                    [--claim_address=<claim_address>] [--funding_account_ids=<funding_account_ids>...]
                    [--preview] [--blocking]

        Options:
            --name=<name>                  : (str) name of the content (can only consist of a-z A-Z 0-9 and -(dash))
            --bid=<bid>                    : (decimal) amount to back the claim
            --file_path=<file_path>        : (str) path to file to be associated with name.
            --file_name=<file_name>        : (str) name of file to be associated with stream.
            --file_hash=<file_hash>        : (str) hash of file to be associated with stream.
            --validate_file                : (bool) validate that the video container and encodings match
                                             common web browser support or that optimization succeeds if specified.
                                             FFmpeg is required
            --optimize_file                : (bool) transcode the video & audio if necessary to ensure
                                             common web browser support. FFmpeg is required
            --fee_currency=<fee_currency>  : (string) specify fee currency
            --fee_amount=<fee_amount>      : (decimal) content download fee
            --fee_address=<fee_address>    : (str) address where to send fee payments, will use
                                                   value from --claim_address if not provided
            --title=<title>                : (str) title of the publication
            --description=<description>    : (str) description of the publication
            --author=<author>              : (str) author of the publication. The usage for this field is not
                                             the same as for channels. The author field is used to credit an author
                                             who is not the publisher and is not represented by the channel. For
                                             example, a pdf file of 'The Odyssey' has an author of 'Homer' but may
                                             by published to a channel such as '@classics', or to no channel at all
            --tags=<tags>                  : (list) add content tags
            --languages=<languages>        : (list) languages used by the channel,
                                                    using RFC 5646 format, eg:
                                                    for English `--languages=en`
                                                    for Spanish (Spain) `--languages=es-ES`
                                                    for Spanish (Mexican) `--languages=es-MX`
                                                    for Chinese (Simplified) `--languages=zh-Hans`
                                                    for Chinese (Traditional) `--languages=zh-Hant`
            --locations=<locations>        : (list) locations relevant to the stream, consisting of 2 letter
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

            --license=<license>            : (str) publication license
            --license_url=<license_url>    : (str) publication license url
            --thumbnail_url=<thumbnail_url>: (str) thumbnail url
            --release_time=<release_time>  : (int) original public release of content, seconds since UNIX epoch
            --width=<width>                : (int) image/video width, automatically calculated from media file
            --height=<height>              : (int) image/video height, automatically calculated from media file
            --duration=<duration>          : (int) audio/video duration in seconds, automatically calculated
            --sd_hash=<sd_hash>            : (str) sd_hash of stream
            --channel_id=<channel_id>      : (str) claim id of the publisher channel
            --channel_name=<channel_name>  : (str) name of publisher channel
          --channel_account_id=<channel_account_id>: (str) one or more account ids for accounts to look in
                                                   for channel certificates, defaults to all accounts.
            --account_id=<account_id>      : (str) account to use for holding the transaction
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
          --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --claim_address=<claim_address>: (str) address where the claim is sent to, if not specified
                                                   it will be determined automatically from the account
            --preview                      : (bool) do not broadcast the transaction
            --blocking                     : (bool) wait until transaction is in mempool

        Returns: {Transaction}
        """
        self.valid_stream_name_or_error(name)
        wallet = self.wallet_manager.get_wallet_or_default(kwargs.get('wallet_id'))
        if kwargs.get('account_id'):
            accounts = [wallet.get_account_or_error(kwargs.get('account_id'))]
        else:
            accounts = wallet.accounts
        claims = await self.ledger.get_claims(
            wallet=wallet, accounts=accounts, claim_name=name
        )
        if len(claims) == 0:
            if 'bid' not in kwargs:
                raise Exception("'bid' is a required argument for new publishes.")
            return await self.jsonrpc_stream_create(name, **kwargs)
        elif len(claims) == 1:
            assert claims[0].claim.is_stream, f"Claim at name '{name}' is not a stream claim."
            return await self.jsonrpc_stream_update(claims[0].claim_id, replace=True, **kwargs)
        raise Exception(
            f"There are {len(claims)} claims for '{name}', please use 'stream update' command "
            f"to update a specific stream claim."
        )

    @requires(WALLET_COMPONENT, FILE_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT)
    async def jsonrpc_stream_repost(self, name, bid, claim_id, allow_duplicate_name=False, channel_id=None,
                                    channel_name=None, channel_account_id=None, account_id=None, wallet_id=None,
                                    claim_address=None, funding_account_ids=None, preview=False, blocking=False):
        """
            Creates a claim that references an existing stream by its claim id.

            Usage:
                stream_repost (<name> | --name=<name>) (<bid> | --bid=<bid>) (<claim_id> | --claim_id=<claim_id>)
                        [--allow_duplicate_name=<allow_duplicate_name>]
                        [--channel_id=<channel_id> | --channel_name=<channel_name>]
                        [--channel_account_id=<channel_account_id>...]
                        [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                        [--claim_address=<claim_address>] [--funding_account_ids=<funding_account_ids>...]
                        [--preview] [--blocking]

            Options:
                --name=<name>                  : (str) name of the content (can only consist of a-z A-Z 0-9 and -(dash))
                --bid=<bid>                    : (decimal) amount to back the claim
                --claim_id=<claim_id>          : (str) id of the claim being reposted
                --allow_duplicate_name=<allow_duplicate_name> : (bool) create new claim even if one already exists with
                                                                       given name. default: false.
                --channel_id=<channel_id>      : (str) claim id of the publisher channel
                --channel_name=<channel_name>  : (str) name of the publisher channel
                --channel_account_id=<channel_account_id>: (str) one or more account ids for accounts to look in
                                                                 for channel certificates, defaults to all accounts.
                --account_id=<account_id>      : (str) account to use for holding the transaction
                --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
                --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
                --claim_address=<claim_address>: (str) address where the claim is sent to, if not specified
                                                       it will be determined automatically from the account
                --preview                      : (bool) do not broadcast the transaction
                --blocking                     : (bool) wait until transaction is in mempool

            Returns: {Transaction}
            """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        self.valid_stream_name_or_error(name)
        account = wallet.get_account_or_default(account_id)
        funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
        channel = await self.get_channel_or_none(wallet, channel_account_id, channel_id, channel_name, for_signing=True)
        amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        claim_address = await self.get_receiving_address(claim_address, account)
        claims = await account.get_claims(claim_name=name)
        if len(claims) > 0:
            if not allow_duplicate_name:
                raise Exception(
                    f"You already have a stream claim published under the name '{name}'. "
                    f"Use --allow-duplicate-name flag to override."
                )
        if not VALID_FULL_CLAIM_ID.fullmatch(claim_id):
            raise Exception('Invalid claim id. It is expected to be a 40 characters long hexadecimal string.')

        claim = Claim()
        claim.repost.reference.claim_id = claim_id
        tx = await Transaction.claim_create(
            name, claim, amount, claim_address, funding_accounts, funding_accounts[0], channel
        )
        new_txo = tx.outputs[0]

        if channel:
            new_txo.sign(channel)
        await tx.sign(funding_accounts)

        if not preview:
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('publish'))
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT, FILE_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT)
    async def jsonrpc_stream_create(
            self, name, bid, file_path=None, allow_duplicate_name=False,
            channel_id=None, channel_name=None, channel_account_id=None,
            account_id=None, wallet_id=None, claim_address=None, funding_account_ids=None,
            preview=False, blocking=False, validate_file=False, optimize_file=False, **kwargs):
        """
        Make a new stream claim and announce the associated file to lbrynet.

        Usage:
            stream_create (<name> | --name=<name>) (<bid> | --bid=<bid>) [<file_path> | --file_path=<file_path>]
                    [--file_name=<file_name>] [--file_hash=<file_hash>] [--validate_file] [--optimize_file]
                    [--allow_duplicate_name=<allow_duplicate_name>]
                    [--fee_currency=<fee_currency>] [--fee_amount=<fee_amount>] [--fee_address=<fee_address>]
                    [--title=<title>] [--description=<description>] [--author=<author>]
                    [--tags=<tags>...] [--languages=<languages>...] [--locations=<locations>...]
                    [--license=<license>] [--license_url=<license_url>] [--thumbnail_url=<thumbnail_url>]
                    [--release_time=<release_time>] [--width=<width>] [--height=<height>] [--duration=<duration>]
                    [--sd_hash=<sd_hash>] [--channel_id=<channel_id> | --channel_name=<channel_name>]
                    [--channel_account_id=<channel_account_id>...]
                    [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                    [--claim_address=<claim_address>] [--funding_account_ids=<funding_account_ids>...]
                    [--preview] [--blocking]

        Options:
            --name=<name>                  : (str) name of the content (can only consist of a-z A-Z 0-9 and -(dash))
            --bid=<bid>                    : (decimal) amount to back the claim
            --file_path=<file_path>        : (str) path to file to be associated with name.
            --file_name=<file_name>        : (str) name of file to be associated with stream.
            --file_hash=<file_hash>        : (str) hash of file to be associated with stream.
            --validate_file                : (bool) validate that the video container and encodings match
                                             common web browser support or that optimization succeeds if specified.
                                             FFmpeg is required
            --optimize_file                : (bool) transcode the video & audio if necessary to ensure
                                             common web browser support. FFmpeg is required
        --allow_duplicate_name=<allow_duplicate_name> : (bool) create new claim even if one already exists with
                                              given name. default: false.
            --fee_currency=<fee_currency>  : (string) specify fee currency
            --fee_amount=<fee_amount>      : (decimal) content download fee
            --fee_address=<fee_address>    : (str) address where to send fee payments, will use
                                                   value from --claim_address if not provided
            --title=<title>                : (str) title of the publication
            --description=<description>    : (str) description of the publication
            --author=<author>              : (str) author of the publication. The usage for this field is not
                                             the same as for channels. The author field is used to credit an author
                                             who is not the publisher and is not represented by the channel. For
                                             example, a pdf file of 'The Odyssey' has an author of 'Homer' but may
                                             by published to a channel such as '@classics', or to no channel at all
            --tags=<tags>                  : (list) add content tags
            --languages=<languages>        : (list) languages used by the channel,
                                                    using RFC 5646 format, eg:
                                                    for English `--languages=en`
                                                    for Spanish (Spain) `--languages=es-ES`
                                                    for Spanish (Mexican) `--languages=es-MX`
                                                    for Chinese (Simplified) `--languages=zh-Hans`
                                                    for Chinese (Traditional) `--languages=zh-Hant`
            --locations=<locations>        : (list) locations relevant to the stream, consisting of 2 letter
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

            --license=<license>            : (str) publication license
            --license_url=<license_url>    : (str) publication license url
            --thumbnail_url=<thumbnail_url>: (str) thumbnail url
            --release_time=<release_time>  : (int) original public release of content, seconds since UNIX epoch
            --width=<width>                : (int) image/video width, automatically calculated from media file
            --height=<height>              : (int) image/video height, automatically calculated from media file
            --duration=<duration>          : (int) audio/video duration in seconds, automatically calculated
            --sd_hash=<sd_hash>            : (str) sd_hash of stream
            --channel_id=<channel_id>      : (str) claim id of the publisher channel
            --channel_name=<channel_name>  : (str) name of the publisher channel
            --channel_account_id=<channel_account_id>: (str) one or more account ids for accounts to look in
                                                   for channel certificates, defaults to all accounts.
            --account_id=<account_id>      : (str) account to use for holding the transaction
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
            --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --claim_address=<claim_address>: (str) address where the claim is sent to, if not specified
                                                   it will be determined automatically from the account
            --preview                      : (bool) do not broadcast the transaction
            --blocking                     : (bool) wait until transaction is in mempool

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        self.valid_stream_name_or_error(name)
        account = wallet.get_account_or_default(account_id)
        funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
        channel = await self.get_channel_or_none(wallet, channel_account_id, channel_id, channel_name, for_signing=True)
        amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        claim_address = await self.get_receiving_address(claim_address, account)
        kwargs['fee_address'] = self.get_fee_address(kwargs, claim_address)

        claims = await account.get_claims(claim_name=name)
        if len(claims) > 0:
            if not allow_duplicate_name:
                raise Exception(
                    f"You already have a stream claim published under the name '{name}'. "
                    f"Use --allow-duplicate-name flag to override."
                )

        if file_path is not None:
            file_path, spec = await self._video_file_analyzer.verify_or_repair(
                validate_file, optimize_file, file_path, ignore_non_video=True
            )
            kwargs.update(spec)

        claim = Claim()
        if file_path is not None:
            claim.stream.update(file_path=file_path, sd_hash='0' * 96, **kwargs)
        else:
            claim.stream.update(**kwargs)
        tx = await Transaction.claim_create(
            name, claim, amount, claim_address, funding_accounts, funding_accounts[0], channel
        )
        new_txo = tx.outputs[0]

        file_stream = None
        if not preview and file_path is not None:
            file_stream = await self.file_manager.create_stream(file_path)
            claim.stream.source.sd_hash = file_stream.sd_hash
            new_txo.script.generate()

        if channel:
            new_txo.sign(channel)
        await tx.sign(funding_accounts)

        if not preview:
            await self.broadcast_or_release(tx, blocking)

            async def save_claims():
                await self.storage.save_claims([self._old_get_temp_claim_info(
                    tx, new_txo, claim_address, claim, name, dewies_to_lbc(amount)
                )])
                if file_path is not None:
                    await self.storage.save_content_claim(file_stream.stream_hash, new_txo.id)

            self.component_manager.loop.create_task(save_claims())
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('publish'))
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT, FILE_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT)
    async def jsonrpc_stream_update(
            self, claim_id, bid=None, file_path=None,
            channel_id=None, channel_name=None, channel_account_id=None, clear_channel=False,
            account_id=None, wallet_id=None, claim_address=None, funding_account_ids=None,
            preview=False, blocking=False, replace=False, validate_file=False, optimize_file=False, **kwargs):
        """
        Update an existing stream claim and if a new file is provided announce it to lbrynet.

        Usage:
            stream_update (<claim_id> | --claim_id=<claim_id>) [--bid=<bid>] [--file_path=<file_path>]
                    [--validate_file] [--optimize_file]
                    [--file_name=<file_name>] [--file_size=<file_size>] [--file_hash=<file_hash>]
                    [--fee_currency=<fee_currency>] [--fee_amount=<fee_amount>]
                    [--fee_address=<fee_address>] [--clear_fee]
                    [--title=<title>] [--description=<description>] [--author=<author>]
                    [--tags=<tags>...] [--clear_tags]
                    [--languages=<languages>...] [--clear_languages]
                    [--locations=<locations>...] [--clear_locations]
                    [--license=<license>] [--license_url=<license_url>] [--thumbnail_url=<thumbnail_url>]
                    [--release_time=<release_time>] [--width=<width>] [--height=<height>] [--duration=<duration>]
                    [--sd_hash=<sd_hash>] [--channel_id=<channel_id> | --channel_name=<channel_name> | --clear_channel]
                    [--channel_account_id=<channel_account_id>...]
                    [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                    [--claim_address=<claim_address>] [--funding_account_ids=<funding_account_ids>...]
                    [--preview] [--blocking] [--replace]

        Options:
            --claim_id=<claim_id>          : (str) id of the stream claim to update
            --bid=<bid>                    : (decimal) amount to back the claim
            --file_path=<file_path>        : (str) path to file to be associated with name.
            --validate_file                : (bool) validate that the video container and encodings match
                                             common web browser support or that optimization succeeds if specified.
                                             FFmpeg is required and file_path must be specified.
            --optimize_file                : (bool) transcode the video & audio if necessary to ensure common
                                             web browser support. FFmpeg is required and file_path must be specified.
            --file_name=<file_name>        : (str) override file name, defaults to name from file_path.
            --file_size=<file_size>        : (str) override file size, otherwise automatically computed.
            --file_hash=<file_hash>        : (str) override file hash, otherwise automatically computed.
            --fee_currency=<fee_currency>  : (string) specify fee currency
            --fee_amount=<fee_amount>      : (decimal) content download fee
            --fee_address=<fee_address>    : (str) address where to send fee payments, will use
                                                   value from --claim_address if not provided
            --clear_fee                    : (bool) clear previously set fee
            --title=<title>                : (str) title of the publication
            --description=<description>    : (str) description of the publication
            --author=<author>              : (str) author of the publication. The usage for this field is not
                                             the same as for channels. The author field is used to credit an author
                                             who is not the publisher and is not represented by the channel. For
                                             example, a pdf file of 'The Odyssey' has an author of 'Homer' but may
                                             by published to a channel such as '@classics', or to no channel at all
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
            --locations=<locations>        : (list) locations relevant to the stream, consisting of 2 letter
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
            --license=<license>            : (str) publication license
            --license_url=<license_url>    : (str) publication license url
            --thumbnail_url=<thumbnail_url>: (str) thumbnail url
            --release_time=<release_time>  : (int) original public release of content, seconds since UNIX epoch
            --width=<width>                : (int) image/video width, automatically calculated from media file
            --height=<height>              : (int) image/video height, automatically calculated from media file
            --duration=<duration>          : (int) audio/video duration in seconds, automatically calculated
            --sd_hash=<sd_hash>            : (str) sd_hash of stream
            --channel_id=<channel_id>      : (str) claim id of the publisher channel
            --channel_name=<channel_name>  : (str) name of the publisher channel
            --clear_channel                : (bool) remove channel signature
          --channel_account_id=<channel_account_id>: (str) one or more account ids for accounts to look in
                                                   for channel certificates, defaults to all accounts.
            --account_id=<account_id>      : (str) account in which to look for stream (default: all)
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
          --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --claim_address=<claim_address>: (str) address where the claim is sent to, if not specified
                                                   it will be determined automatically from the account
            --preview                      : (bool) do not broadcast the transaction
            --blocking                     : (bool) wait until transaction is in mempool
            --replace                      : (bool) instead of modifying specific values on
                                                    the stream, this will clear all existing values
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

        existing_claims = await self.ledger.get_claims(
            wallet=wallet, accounts=accounts, claim_id=claim_id
        )
        if len(existing_claims) != 1:
            account_ids = ', '.join(f"'{account.id}'" for account in accounts)
            raise Exception(
                f"Can't find the stream '{claim_id}' in account(s) {account_ids}."
            )
        old_txo = existing_claims[0]
        if not old_txo.claim.is_stream:
            raise Exception(
                f"A claim with id '{claim_id}' was found but it is not a stream claim."
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

        file_path, spec = await self._video_file_analyzer.verify_or_repair(
            validate_file, optimize_file, file_path, ignore_non_video=True
        )
        kwargs.update(spec)

        if replace:
            claim = Claim()
            if old_txo.claim.stream.has_source:
                claim.stream.message.source.CopyFrom(
                    old_txo.claim.stream.message.source
                )
            stream_type = old_txo.claim.stream.stream_type
            if stream_type:
                old_stream_type = getattr(old_txo.claim.stream.message, stream_type)
                new_stream_type = getattr(claim.stream.message, stream_type)
                new_stream_type.CopyFrom(old_stream_type)
            claim.stream.update(file_path=file_path, **kwargs)
        else:
            claim = Claim.from_bytes(old_txo.claim.to_bytes())
            claim.stream.update(file_path=file_path, **kwargs)
        tx = await Transaction.claim_update(
            old_txo, claim, amount, claim_address, funding_accounts, funding_accounts[0], channel
        )
        new_txo = tx.outputs[0]

        stream_hash = None
        if not preview:
            old_stream = self.file_manager.get_filtered(sd_hash=old_txo.claim.stream.source.sd_hash)
            old_stream = old_stream[0] if old_stream else None
            if file_path is not None:
                if old_stream:
                    await self.file_manager.delete(old_stream, delete_file=False)
                file_stream = await self.file_manager.create_stream(file_path)
                new_txo.claim.stream.source.sd_hash = file_stream.sd_hash
                new_txo.script.generate()
                stream_hash = file_stream.stream_hash
            elif old_stream:
                stream_hash = old_stream.stream_hash

        if channel:
            new_txo.sign(channel)
        await tx.sign(funding_accounts)

        if not preview:
            await self.broadcast_or_release(tx, blocking)

            async def save_claims():
                await self.storage.save_claims([self._old_get_temp_claim_info(
                    tx, new_txo, claim_address, new_txo.claim, new_txo.claim_name, dewies_to_lbc(amount)
                )])
                if stream_hash:
                    await self.storage.save_content_claim(stream_hash, new_txo.id)

            self.component_manager.loop.create_task(save_claims())
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('publish'))
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    async def jsonrpc_stream_abandon(
            self, claim_id=None, txid=None, nout=None, account_id=None, wallet_id=None,
            preview=False, blocking=False):
        """
        Abandon one of my stream claims.

        Usage:
            stream_abandon [<claim_id> | --claim_id=<claim_id>]
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
            [Input.spend(txo) for txo in claims], [], accounts, account
        )

        if not preview:
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('abandon'))
        else:
            await self.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    def jsonrpc_stream_list(self, *args, **kwargs):
        """
        List my stream claims.

        Usage:
            stream_list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]
                        [--name=<name>...] [--claim_id=<claim_id>...] [--is_spent]
                        [--page=<page>] [--page_size=<page_size>] [--resolve] [--no_totals]

        Options:
            --name=<name>              : (str or list) stream name
            --claim_id=<claim_id>      : (str or list) stream id
            --is_spent                 : (bool) shows previous stream updates and abandons
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination
            --resolve                  : (bool) resolves each stream to provide additional metadata
            --no_totals                : (bool) do not calculate the total number of pages and items in result set
                                                (significant performance boost)

        Returns: {Paginated[Output]}
        """
        kwargs['type'] = 'stream'
        if 'is_spent' not in kwargs:
            kwargs['is_not_spent'] = True
        return self.jsonrpc_txo_list(*args, **kwargs)

    @requires(WALLET_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, BLOB_COMPONENT,
              DHT_COMPONENT, DATABASE_COMPONENT)
    def jsonrpc_stream_cost_estimate(self, uri):
        """
        Get estimated cost for a lbry stream

        Usage:
            stream_cost_estimate (<uri> | --uri=<uri>)

        Options:
            --uri=<uri>      : (str) uri to use

        Returns:
            (float) Estimated cost in lbry credits, returns None if uri is not
                resolvable
        """
        return self.get_est_cost_from_uri(uri)
