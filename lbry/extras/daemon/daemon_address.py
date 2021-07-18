#!/usr/bin/env python3
"""
Basic class with address methods for the Daemon class (JSON-RPC server).
"""
from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.daemon_meta import paginate_rows
from lbry.extras.daemon.components import WALLET_COMPONENT


class Daemon_address(metaclass=JSONRPCServerType):
    @requires(WALLET_COMPONENT)
    async def jsonrpc_address_is_mine(self, address, account_id=None, wallet_id=None):
        """
        Checks if an address is associated with the current wallet.

        Usage:
            address_is_mine (<address> | --address=<address>)
                            [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]

        Options:
            --address=<address>       : (str) address to check
            --account_id=<account_id> : (str) id of the account to use
            --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet

        Returns:
            (bool) true, if address is associated with current wallet
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        account = wallet.get_account_or_default(account_id)
        match = await self.ledger.db.get_address(read_only=True, address=address, accounts=[account])
        if match is not None:
            return True
        return False

    @requires(WALLET_COMPONENT)
    def jsonrpc_address_list(self, address=None, account_id=None, wallet_id=None, page=None, page_size=None):
        """
        List account addresses or details of single address.

        Usage:
            address_list [--address=<address>] [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                         [--page=<page>] [--page_size=<page_size>]

        Options:
            --address=<address>        : (str) just show details for single address
            --account_id=<account_id>  : (str) id of the account to use
            --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns: {Paginated[Address]}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        constraints = {
            'cols': ('address', 'account', 'used_times', 'pubkey', 'chain_code', 'n', 'depth')
        }
        if address:
            constraints['address'] = address
        if account_id:
            constraints['accounts'] = [wallet.get_account_or_error(account_id)]
        else:
            constraints['accounts'] = wallet.accounts
        return paginate_rows(
            self.ledger.get_addresses,
            self.ledger.get_address_count,
            page, page_size, read_only=True, **constraints
        )

    @requires(WALLET_COMPONENT)
    def jsonrpc_address_unused(self, account_id=None, wallet_id=None):
        """
        Return an address containing no balance, will create
        a new address if there is none.

        Usage:
            address_unused [--account_id=<account_id>] [--wallet_id=<wallet_id>]

        Options:
            --account_id=<account_id> : (str) id of the account to use
            --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet

        Returns: {Address}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        return wallet.get_account_or_default(account_id).receiving.get_or_create_usable_address()
