#!/usr/bin/env python3
"""
Basic class with wallet methods for the Daemon class (JSON-RPC server).
"""
import os

from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.daemon_meta import paginate_list
from lbry.extras.daemon.components import WALLET_COMPONENT
from lbry.wallet import (Account, SingleKey, HierarchicalDeterministic,
                         Output, Transaction)
from lbry.wallet.dewies import dict_values_to_lbc


class Daemon_wallet(metaclass=JSONRPCServerType):
    @requires("wallet")
    def jsonrpc_wallet_list(self, wallet_id=None, page=None, page_size=None):
        """
        List wallets.

        Usage:
            wallet_list [--wallet_id=<wallet_id>] [--page=<page>] [--page_size=<page_size>]

        Options:
            --wallet_id=<wallet_id>  : (str) show specific wallet only
            --page=<page>            : (int) page to return during paginating
            --page_size=<page_size>  : (int) number of items on page during pagination

        Returns: {Paginated[Wallet]}
        """
        if wallet_id:
            return paginate_list([self.wallet_manager.get_wallet_or_error(wallet_id)], 1, 1)
        return paginate_list(self.wallet_manager.wallets, page, page_size)

    def jsonrpc_wallet_reconnect(self):
        """
        Reconnects ledger network client, applying new configurations.

        Usage:
            wallet_reconnect

        Options:

        Returns: None
        """
        return self.wallet_manager.reset()

    @requires("wallet")
    async def jsonrpc_wallet_create(
            self, wallet_id, skip_on_startup=False, create_account=False, single_key=False):
        """
        Create a new wallet.

        Usage:
            wallet_create (<wallet_id> | --wallet_id=<wallet_id>) [--skip_on_startup]
                          [--create_account] [--single_key]

        Options:
            --wallet_id=<wallet_id>  : (str) wallet file name
            --skip_on_startup        : (bool) don't add wallet to daemon_settings.yml
            --create_account         : (bool) generates the default account
            --single_key             : (bool) used with --create_account, creates single-key account

        Returns: {Wallet}
        """
        wallet_path = os.path.join(self.conf.wallet_dir, 'wallets', wallet_id)
        for wallet in self.wallet_manager.wallets:
            if wallet.id == wallet_id:
                raise Exception(f"Wallet at path '{wallet_path}' already exists and is loaded.")
        if os.path.exists(wallet_path):
            raise Exception(f"Wallet at path '{wallet_path}' already exists, use 'wallet_add' to load wallet.")

        wallet = self.wallet_manager.import_wallet(wallet_path)
        if not wallet.accounts and create_account:
            account = Account.generate(
                self.ledger, wallet, address_generator={
                    'name': SingleKey.name if single_key else HierarchicalDeterministic.name
                }
            )
            if self.ledger.network.is_connected:
                await self.ledger.subscribe_account(account)
        wallet.save()
        if not skip_on_startup:
            with self.conf.update_config() as c:
                c.wallets += [wallet_id]
        return wallet

    @requires("wallet")
    async def jsonrpc_wallet_add(self, wallet_id):
        """
        Add existing wallet.

        Usage:
            wallet_add (<wallet_id> | --wallet_id=<wallet_id>)

        Options:
            --wallet_id=<wallet_id>  : (str) wallet file name

        Returns: {Wallet}
        """
        wallet_path = os.path.join(self.conf.wallet_dir, 'wallets', wallet_id)
        for wallet in self.wallet_manager.wallets:
            if wallet.id == wallet_id:
                raise Exception(f"Wallet at path '{wallet_path}' is already loaded.")
        if not os.path.exists(wallet_path):
            raise Exception(f"Wallet at path '{wallet_path}' was not found.")
        wallet = self.wallet_manager.import_wallet(wallet_path)
        if self.ledger.network.is_connected:
            for account in wallet.accounts:
                await self.ledger.subscribe_account(account)
        return wallet

    @requires("wallet")
    async def jsonrpc_wallet_remove(self, wallet_id):
        """
        Remove an existing wallet.

        Usage:
            wallet_remove (<wallet_id> | --wallet_id=<wallet_id>)

        Options:
            --wallet_id=<wallet_id>    : (str) name of wallet to remove

        Returns: {Wallet}
        """
        wallet = self.wallet_manager.get_wallet_or_error(wallet_id)
        self.wallet_manager.wallets.remove(wallet)
        for account in wallet.accounts:
            await self.ledger.unsubscribe_account(account)
        return wallet

    @requires("wallet")
    async def jsonrpc_wallet_balance(self, wallet_id=None, confirmations=0):
        """
        Return the balance of a wallet

        Usage:
            wallet_balance [--wallet_id=<wallet_id>] [--confirmations=<confirmations>]

        Options:
            --wallet_id=<wallet_id>         : (str) balance for specific wallet
            --confirmations=<confirmations> : (int) Only include transactions with this many
                                              confirmed blocks.

        Returns:
            (decimal) amount of lbry credits in wallet
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        balance = await self.ledger.get_detailed_balance(
            accounts=wallet.accounts, confirmations=confirmations
        )
        return dict_values_to_lbc(balance)

    def jsonrpc_wallet_status(self, wallet_id=None):
        """
        Status of wallet including encryption/lock state.

        Usage:
            wallet_status [<wallet_id> | --wallet_id=<wallet_id>]

        Options:
            --wallet_id=<wallet_id>    : (str) status of specific wallet

        Returns:
            Dictionary of wallet status information.
        """
        if self.wallet_manager is None:
            return {'is_encrypted': None, 'is_syncing': None, 'is_locked': None}
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        return {
            'is_encrypted': wallet.is_encrypted,
            'is_syncing': len(self.ledger._update_tasks) > 0,
            'is_locked': wallet.is_locked
        }

    @requires(WALLET_COMPONENT)
    def jsonrpc_wallet_unlock(self, password, wallet_id=None):
        """
        Unlock an encrypted wallet

        Usage:
            wallet_unlock (<password> | --password=<password>) [--wallet_id=<wallet_id>]

        Options:
            --password=<password>      : (str) password to use for unlocking
            --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet

        Returns:
            (bool) true if wallet is unlocked, otherwise false
        """
        return self.wallet_manager.get_wallet_or_default(wallet_id).unlock(password)

    @requires(WALLET_COMPONENT)
    def jsonrpc_wallet_lock(self, wallet_id=None):
        """
        Lock an unlocked wallet

        Usage:
            wallet_lock [--wallet_id=<wallet_id>]

        Options:
            --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet

        Returns:
            (bool) true if wallet is locked, otherwise false
        """
        return self.wallet_manager.get_wallet_or_default(wallet_id).lock()

    @requires(WALLET_COMPONENT)
    def jsonrpc_wallet_decrypt(self, wallet_id=None):
        """
        Decrypt an encrypted wallet, this will remove the wallet password. The wallet must be unlocked to decrypt it

        Usage:
            wallet_decrypt [--wallet_id=<wallet_id>]

        Options:
            --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet

        Returns:
            (bool) true if wallet is decrypted, otherwise false
        """
        return self.wallet_manager.get_wallet_or_default(wallet_id).decrypt()

    @requires(WALLET_COMPONENT)
    def jsonrpc_wallet_encrypt(self, new_password, wallet_id=None):
        """
        Encrypt an unencrypted wallet with a password

        Usage:
            wallet_encrypt (<new_password> | --new_password=<new_password>)
                            [--wallet_id=<wallet_id>]

        Options:
            --new_password=<new_password>  : (str) password to encrypt account
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet

        Returns:
            (bool) true if wallet is decrypted, otherwise false
        """
        return self.wallet_manager.get_wallet_or_default(wallet_id).encrypt(new_password)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_wallet_send(
            self, amount, addresses, wallet_id=None,
            change_account_id=None, funding_account_ids=None, preview=False, blocking=True):
        """
        Send the same number of credits to multiple addresses using all accounts in wallet to
        fund the transaction and the default account to receive any change.

        Usage:
            wallet_send <amount> <addresses>... [--wallet_id=<wallet_id>] [--preview]
                        [--change_account_id=None] [--funding_account_ids=<funding_account_ids>...]
                        [--blocking]

        Options:
            --wallet_id=<wallet_id>         : (str) restrict operation to specific wallet
            --change_account_id=<wallet_id> : (str) account where change will go
            --funding_account_ids=<funding_account_ids> : (str) accounts to fund the transaction
            --preview                       : (bool) do not broadcast the transaction
            --blocking                      : (bool) wait until tx has synced

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        account = wallet.get_account_or_default(change_account_id)
        accounts = wallet.get_accounts_or_all(funding_account_ids)

        amount = self.get_dewies_or_error("amount", amount)

        if addresses and not isinstance(addresses, list):
            addresses = [addresses]

        outputs = []
        for address in addresses:
            self.valid_address_or_error(address, allow_script_address=True)
            if self.ledger.is_pubkey_address(address):
                outputs.append(
                    Output.pay_pubkey_hash(
                        amount, self.ledger.address_to_hash160(address)
                    )
                )
            elif self.ledger.is_script_address(address):
                outputs.append(
                    Output.pay_script_hash(
                        amount, self.ledger.address_to_hash160(address)
                    )
                )
            else:
                raise ValueError(f"Unsupported address: '{address}'")

        tx = await Transaction.create(
            [], outputs, accounts, account
        )
        if not preview:
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.analytics_manager.send_credits_sent())
        else:
            await self.ledger.release_tx(tx)
        return tx
