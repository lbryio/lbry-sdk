#!/usr/bin/env python3
"""
Basic class with utxo methods for the Daemon class (JSON-RPC server).
"""
from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.components import WALLET_COMPONENT


class Daemon_utxo(metaclass=JSONRPCServerType):
    @requires(WALLET_COMPONENT)
    def jsonrpc_utxo_list(self, *args, **kwargs):
        """
        List unspent transaction outputs

        Usage:
            utxo_list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]
                      [--page=<page>] [--page_size=<page_size>]

        Options:
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns: {Paginated[Output]}
        """
        kwargs['type'] = ['other', 'purchase']
        kwargs['is_not_spent'] = True
        return self.jsonrpc_txo_list(*args, **kwargs)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_utxo_release(self, account_id=None, wallet_id=None):
        """
        When spending a UTXO it is locally locked to prevent double spends;
        occasionally this can result in a UTXO being locked which ultimately
        did not get spent (failed to broadcast, spend transaction was not
        accepted by blockchain node, etc). This command releases the lock
        on all UTXOs in your account.

        Usage:
            utxo_release [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]

        Options:
            --account_id=<account_id> : (str) id of the account to query
            --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet

        Returns:
            None
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        if account_id is not None:
            await wallet.get_account_or_error(account_id).release_all_outputs()
        else:
            for account in wallet.accounts:
                await account.release_all_outputs()
