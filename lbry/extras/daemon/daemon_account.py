#!/usr/bin/env python3
"""
Basic class with account methods for the Daemon class (JSON-RPC server).
"""
import time

from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.daemon_meta import paginate_list
from lbry.extras.daemon.components import WALLET_COMPONENT
from lbry.wallet import Account, SingleKey, HierarchicalDeterministic
from lbry.wallet.dewies import dict_values_to_lbc


class Daemon_account(metaclass=JSONRPCServerType):
    @requires("wallet")
    async def jsonrpc_account_list(
            self, account_id=None, wallet_id=None, confirmations=0,
            include_claims=False, show_seed=False, page=None, page_size=None):
        """
        List details of all of the accounts or a specific account.

        Usage:
            account_list [<account_id>] [--wallet_id=<wallet_id>]
                         [--confirmations=<confirmations>]
                         [--include_claims] [--show_seed]
                         [--page=<page>] [--page_size=<page_size>]

        Options:
            --account_id=<account_id>       : (str) If provided only the balance for this
                                                    account will be given
            --wallet_id=<wallet_id>         : (str) accounts in specific wallet
            --confirmations=<confirmations> : (int) required confirmations (default: 0)
            --include_claims                : (bool) include claims, requires than a
                                                     LBC account is specified (default: false)
            --show_seed                     : (bool) show the seed for the account
            --page=<page>                   : (int) page to return during paginating
            --page_size=<page_size>         : (int) number of items on page during pagination

        Returns: {Paginated[Account]}
        """
        kwargs = {
            'confirmations': confirmations,
            'show_seed': show_seed
        }
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        if account_id:
            return paginate_list([await wallet.get_account_or_error(account_id).get_details(**kwargs)], 1, 1)
        else:
            return paginate_list(await wallet.get_detailed_accounts(**kwargs), page, page_size)

    @requires("wallet")
    async def jsonrpc_account_balance(self, account_id=None, wallet_id=None, confirmations=0):
        """
        Return the balance of an account

        Usage:
            account_balance [<account_id>] [<address> | --address=<address>] [--wallet_id=<wallet_id>]
                            [<confirmations> | --confirmations=<confirmations>]

        Options:
            --account_id=<account_id>       : (str) If provided only the balance for this
                                              account will be given. Otherwise default account.
            --wallet_id=<wallet_id>         : (str) balance for specific wallet
            --confirmations=<confirmations> : (int) Only include transactions with this many
                                              confirmed blocks.

        Returns:
            (decimal) amount of lbry credits in wallet
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        account = wallet.get_account_or_default(account_id)
        balance = await account.get_detailed_balance(
            confirmations=confirmations, read_only=True
        )
        return dict_values_to_lbc(balance)

    @requires("wallet")
    async def jsonrpc_account_add(
            self, account_name, wallet_id=None, single_key=False,
            seed=None, private_key=None, public_key=None):
        """
        Add a previously created account from a seed, private key or public key (read-only).
        Specify --single_key for single address or vanity address accounts.

        Usage:
            account_add (<account_name> | --account_name=<account_name>)
                 (--seed=<seed> | --private_key=<private_key> | --public_key=<public_key>)
                 [--single_key] [--wallet_id=<wallet_id>]

        Options:
            --account_name=<account_name>  : (str) name of the account to add
            --seed=<seed>                  : (str) seed to generate new account from
            --private_key=<private_key>    : (str) private key for new account
            --public_key=<public_key>      : (str) public key for new account
            --single_key                   : (bool) create single key account, default is multi-key
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet

        Returns: {Account}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        account = Account.from_dict(
            self.ledger, wallet, {
                'name': account_name,
                'seed': seed,
                'private_key': private_key,
                'public_key': public_key,
                'address_generator': {
                    'name': SingleKey.name if single_key else HierarchicalDeterministic.name
                }
            }
        )
        wallet.save()
        if self.ledger.network.is_connected:
            await self.ledger.subscribe_account(account)
        return account

    @requires("wallet")
    async def jsonrpc_account_create(self, account_name, single_key=False, wallet_id=None):
        """
        Create a new account. Specify --single_key if you want to use
        the same address for all transactions (not recommended).

        Usage:
            account_create (<account_name> | --account_name=<account_name>)
                           [--single_key] [--wallet_id=<wallet_id>]

        Options:
            --account_name=<account_name>  : (str) name of the account to create
            --single_key                   : (bool) create single key account, default is multi-key
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet

        Returns: {Account}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        account = Account.generate(
            self.ledger, wallet, account_name, {
                'name': SingleKey.name if single_key else HierarchicalDeterministic.name
            }
        )
        wallet.save()
        if self.ledger.network.is_connected:
            await self.ledger.subscribe_account(account)
        return account

    @requires("wallet")
    def jsonrpc_account_remove(self, account_id, wallet_id=None):
        """
        Remove an existing account.

        Usage:
            account_remove (<account_id> | --account_id=<account_id>) [--wallet_id=<wallet_id>]

        Options:
            --account_id=<account_id>  : (str) id of the account to remove
            --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet

        Returns: {Account}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        account = wallet.get_account_or_error(account_id)
        wallet.accounts.remove(account)
        wallet.save()
        return account

    @requires("wallet")
    def jsonrpc_account_set(
            self, account_id, wallet_id=None, default=False, new_name=None,
            change_gap=None, change_max_uses=None, receiving_gap=None, receiving_max_uses=None):
        """
        Change various settings on an account.

        Usage:
            account_set (<account_id> | --account_id=<account_id>) [--wallet_id=<wallet_id>]
                [--default] [--new_name=<new_name>]
                [--change_gap=<change_gap>] [--change_max_uses=<change_max_uses>]
                [--receiving_gap=<receiving_gap>] [--receiving_max_uses=<receiving_max_uses>]

        Options:
            --account_id=<account_id>       : (str) id of the account to change
            --wallet_id=<wallet_id>         : (str) restrict operation to specific wallet
            --default                       : (bool) make this account the default
            --new_name=<new_name>           : (str) new name for the account
            --receiving_gap=<receiving_gap> : (int) set the gap for receiving addresses
            --receiving_max_uses=<receiving_max_uses> : (int) set the maximum number of times to
                                                              use a receiving address
            --change_gap=<change_gap>           : (int) set the gap for change addresses
            --change_max_uses=<change_max_uses> : (int) set the maximum number of times to
                                                        use a change address

        Returns: {Account}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        account = wallet.get_account_or_error(account_id)
        change_made = False

        if account.receiving.name == HierarchicalDeterministic.name:
            address_changes = {
                'change': {'gap': change_gap, 'maximum_uses_per_address': change_max_uses},
                'receiving': {'gap': receiving_gap, 'maximum_uses_per_address': receiving_max_uses},
            }
            for chain_name in address_changes:
                chain = getattr(account, chain_name)
                for attr, value in address_changes[chain_name].items():
                    if value is not None:
                        setattr(chain, attr, value)
                        change_made = True

        if new_name is not None:
            account.name = new_name
            change_made = True

        if default and wallet.default_account != account:
            wallet.accounts.remove(account)
            wallet.accounts.insert(0, account)
            change_made = True

        if change_made:
            account.modified_on = int(time.time())
            wallet.save()

        return account

    @requires("wallet")
    def jsonrpc_account_max_address_gap(self, account_id, wallet_id=None):
        """
        Finds ranges of consecutive addresses that are unused and returns the length
        of the longest such range: for change and receiving address chains. This is
        useful to figure out ideal values to set for 'receiving_gap' and 'change_gap'
        account settings.

        Usage:
            account_max_address_gap (<account_id> | --account_id=<account_id>)
                                    [--wallet_id=<wallet_id>]

        Options:
            --account_id=<account_id>  : (str) account for which to get max gaps
            --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet

        Returns:
            (map) maximum gap for change and receiving addresses
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        return wallet.get_account_or_error(account_id).get_max_gap()

    @requires("wallet")
    def jsonrpc_account_fund(self, to_account=None, from_account=None, amount='0.0',
                             everything=False, outputs=1, broadcast=False, wallet_id=None):
        """
        Transfer some amount (or --everything) to an account from another
        account (can be the same account). Amounts are interpreted as LBC.
        You can also spread the transfer across a number of --outputs (cannot
        be used together with --everything).

        Usage:
            account_fund [<to_account> | --to_account=<to_account>]
                [<from_account> | --from_account=<from_account>]
                (<amount> | --amount=<amount> | --everything)
                [<outputs> | --outputs=<outputs>] [--wallet_id=<wallet_id>]
                [--broadcast]

        Options:
            --to_account=<to_account>     : (str) send to this account
            --from_account=<from_account> : (str) spend from this account
            --amount=<amount>             : (str) the amount to transfer lbc
            --everything                  : (bool) transfer everything (excluding claims), default: false.
            --outputs=<outputs>           : (int) split payment across many outputs, default: 1.
            --wallet_id=<wallet_id>       : (str) limit operation to specific wallet.
            --broadcast                   : (bool) actually broadcast the transaction, default: false.

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        to_account = wallet.get_account_or_default(to_account)
        from_account = wallet.get_account_or_default(from_account)
        amount = self.get_dewies_or_error('amount', amount) if amount else None
        if not isinstance(outputs, int):
            raise ValueError("--outputs must be an integer.")
        if everything and outputs > 1:
            raise ValueError("Using --everything along with --outputs is not supported.")
        return from_account.fund(
            to_account=to_account, amount=amount, everything=everything,
            outputs=outputs, broadcast=broadcast
        )

    @requires(WALLET_COMPONENT)
    def jsonrpc_account_send(self, amount, addresses, account_id=None, wallet_id=None, preview=False, blocking=False):
        """
        Send the same number of credits to multiple addresses from a specific account (or default account).

        Usage:
            account_send <amount> <addresses>... [--account_id=<account_id>] [--wallet_id=<wallet_id>] [--preview]
                                                 [--blocking]

        Options:
            --account_id=<account_id>  : (str) account to fund the transaction
            --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet
            --preview                  : (bool) do not broadcast the transaction
            --blocking                 : (bool) wait until tx has synced

        Returns: {Transaction}
        """
        return self.jsonrpc_wallet_send(
            amount=amount, addresses=addresses, wallet_id=wallet_id,
            change_account_id=account_id, funding_account_ids=[account_id] if account_id else [],
            preview=preview, blocking=blocking
        )
