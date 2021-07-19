#!/usr/bin/env python3
"""
Basic class with support methods for the Daemon class (JSON-RPC server).
"""
from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.daemon_meta import DEFAULT_PAGE_SIZE
from lbry.extras.daemon.components import WALLET_COMPONENT
from lbry.wallet import Input, Output, Transaction
from lbry.wallet.dewies import dewies_to_lbc


class Daemon_support(metaclass=JSONRPCServerType):
    @requires(WALLET_COMPONENT)
    async def jsonrpc_support_create(
            self, claim_id, amount, tip=False,
            channel_id=None, channel_name=None, channel_account_id=None,
            account_id=None, wallet_id=None, funding_account_ids=None,
            comment=None, preview=False, blocking=False):
        """
        Create a support or a tip for name claim.

        Usage:
            support_create (<claim_id> | --claim_id=<claim_id>) (<amount> | --amount=<amount>)
                           [--tip] [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                           [--channel_id=<channel_id> | --channel_name=<channel_name>]
                           [--channel_account_id=<channel_account_id>...] [--comment=<comment>]
                           [--preview] [--blocking] [--funding_account_ids=<funding_account_ids>...]

        Options:
            --claim_id=<claim_id>         : (str) claim_id of the claim to support
            --amount=<amount>             : (decimal) amount of support
            --tip                         : (bool) send support to claim owner, default: false.
            --channel_id=<channel_id>     : (str) claim id of the supporters identity channel
            --channel_name=<channel_name> : (str) name of the supporters identity channel
          --channel_account_id=<channel_account_id>: (str) one or more account ids for accounts to look in
                                                   for channel certificates, defaults to all accounts.
            --account_id=<account_id>     : (str) account to use for holding the transaction
            --wallet_id=<wallet_id>       : (str) restrict operation to specific wallet
          --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --comment=<comment>           : (str) add a comment to the support
            --preview                     : (bool) do not broadcast the transaction
            --blocking                    : (bool) wait until transaction is in mempool

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
        channel = await self.get_channel_or_none(wallet, channel_account_id, channel_id, channel_name, for_signing=True)
        amount = self.get_dewies_or_error("amount", amount)
        claim = await self.ledger.get_claim_by_claim_id(wallet.accounts, claim_id)
        claim_address = claim.get_address(self.ledger)
        if not tip:
            account = wallet.get_account_or_default(account_id)
            claim_address = await account.receiving.get_or_create_usable_address()

        tx = await Transaction.support(
            claim.claim_name, claim_id, amount, claim_address, funding_accounts, funding_accounts[0], channel,
            comment=comment
        )
        new_txo = tx.outputs[0]

        if channel:
            new_txo.sign(channel)
        await tx.sign(funding_accounts)

        if not preview:
            await self.broadcast_or_release(tx, blocking)
            await self.storage.save_supports({claim_id: [{
                'txid': tx.id,
                'nout': tx.position,
                'address': claim_address,
                'claim_id': claim_id,
                'amount': dewies_to_lbc(amount)
            }]})
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('new_support'))
        else:
            await self.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    def jsonrpc_support_list(self, *args, received=False, sent=False, staked=False, **kwargs):
        """
        List staked supports and sent/received tips.

        Usage:
            support_list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]
                         [--name=<name>...] [--claim_id=<claim_id>...]
                         [--received | --sent | --staked] [--is_spent]
                         [--page=<page>] [--page_size=<page_size>] [--no_totals]

        Options:
            --name=<name>              : (str or list) claim name
            --claim_id=<claim_id>      : (str or list) claim id
            --received                 : (bool) only show received (tips)
            --sent                     : (bool) only show sent (tips)
            --staked                   : (bool) only show my staked supports
            --is_spent                 : (bool) show abandoned supports
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination
            --no_totals                : (bool) do not calculate the total number of pages and items in result set
                                                (significant performance boost)

        Returns: {Paginated[Output]}
        """
        kwargs['type'] = 'support'
        if 'is_spent' not in kwargs:
            kwargs['is_not_spent'] = True
        if received:
            kwargs['is_not_my_input'] = True
            kwargs['is_my_output'] = True
        elif sent:
            kwargs['is_my_input'] = True
            kwargs['is_not_my_output'] = True
            # spent for not my outputs is undetermined
            kwargs.pop('is_spent', None)
            kwargs.pop('is_not_spent', None)
        elif staked:
            kwargs['is_my_input'] = True
            kwargs['is_my_output'] = True
        return self.jsonrpc_txo_list(*args, **kwargs)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_support_abandon(
            self, claim_id=None, txid=None, nout=None, keep=None,
            account_id=None, wallet_id=None, preview=False, blocking=False):
        """
        Abandon supports, including tips, of a specific claim, optionally
        keeping some amount as supports.

        Usage:
            support_abandon [--claim_id=<claim_id>] [(--txid=<txid> --nout=<nout>)] [--keep=<keep>]
                            [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                            [--preview] [--blocking]

        Options:
            --claim_id=<claim_id>     : (str) claim_id of the support to abandon
            --txid=<txid>             : (str) txid of the claim to abandon
            --nout=<nout>             : (int) nout of the claim to abandon
            --keep=<keep>             : (decimal) amount of lbc to keep as support
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
            supports = await self.ledger.get_supports(
                wallet=wallet, accounts=accounts, **{'txo.txid': txid, 'txo.position': nout}
            )
        elif claim_id is not None:
            supports = await self.ledger.get_supports(
                wallet=wallet, accounts=accounts, claim_id=claim_id
            )
        else:
            raise Exception('Must specify claim_id, or txid and nout')

        if not supports:
            raise Exception('No supports found for the specified claim_id or txid:nout')

        if keep is not None:
            keep = self.get_dewies_or_error('keep', keep)
        else:
            keep = 0

        outputs = []
        if keep > 0:
            outputs = [
                Output.pay_support_pubkey_hash(
                    keep, supports[0].claim_name, supports[0].claim_id, supports[0].pubkey_hash
                )
            ]

        tx = await Transaction.create(
            [Input.spend(txo) for txo in supports], outputs, accounts, account
        )

        if not preview:
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('abandon'))
        else:
            await self.ledger.release_tx(tx)

        return tx

    async def jsonrpc_support_sum(self, claim_id, new_sdk_server, include_channel_content=False, **kwargs):
        """
        List total staked supports for a claim, grouped by the channel that signed the support.

        If claim_id is a channel claim, you can use --include_channel_content to also include supports for
        content claims in the channel.

        !!!! NOTE: PAGINATION DOES NOT DO ANYTHING AT THE MOMENT !!!!!

        Usage:
            support_sum <claim_id> <new_sdk_server>
                         [--include_channel_content]
                         [--page=<page>] [--page_size=<page_size>]

        Options:
            --claim_id=<claim_id>             : (str)  claim id
            --new_sdk_server=<new_sdk_server> : (str)  URL of the new SDK server (EXPERIMENTAL)
            --include_channel_content         : (bool) if claim_id is for a channel, include supports for claims in
                                                       that channel
            --page=<page>                     : (int)  page to return during paginating
            --page_size=<page_size>           : (int)  number of items on page during pagination

        Returns: {Paginated[Dict]}
        """
        page_num, page_size = abs(kwargs.pop('page', 1)), min(abs(kwargs.pop('page_size', DEFAULT_PAGE_SIZE)), 50)
        kwargs.update({'offset': page_size * (page_num - 1), 'limit': page_size})
        support_sums = await self.ledger.sum_supports(
            new_sdk_server, claim_id=claim_id, include_channel_content=include_channel_content, **kwargs
        )
        return {
            "items": support_sums,
            "page": page_num,
            "page_size": page_size
        }
