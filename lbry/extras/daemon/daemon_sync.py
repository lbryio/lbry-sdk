#!/usr/bin/env python3
"""
Basic class with synchronizing methods for the Daemon class (JSON-RPC server).
"""
import asyncio
from binascii import hexlify

from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires
from lbry.wallet import ENCRYPT_ON_DISK


class Daemon_sync(metaclass=JSONRPCServerType):
    @requires("wallet")
    def jsonrpc_sync_hash(self, wallet_id=None):
        """
        Deterministic hash of the wallet.

        Usage:
            sync_hash [<wallet_id> | --wallet_id=<wallet_id>]

        Options:
            --wallet_id=<wallet_id>   : (str) wallet for which to generate hash

        Returns:
            (str) sha256 hash of wallet
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        return hexlify(wallet.hash).decode()

    @requires("wallet")
    async def jsonrpc_sync_apply(self, password, data=None, wallet_id=None, blocking=False):
        """
        Apply incoming synchronization data, if provided, and return a sync hash and update wallet data.

        Wallet must be unlocked to perform this operation.

        If "encrypt-on-disk" preference is True and supplied password is different from local password,
        or there is no local password (because local wallet was not encrypted), then the supplied password
        will be used for local encryption (overwriting previous local encryption password).

        Usage:
            sync_apply <password> [--data=<data>] [--wallet_id=<wallet_id>] [--blocking]

        Options:
            --password=<password>         : (str) password to decrypt incoming and encrypt outgoing data
            --data=<data>                 : (str) incoming sync data, if any
            --wallet_id=<wallet_id>       : (str) wallet being sync'ed
            --blocking                    : (bool) wait until any new accounts have sync'ed

        Returns:
            (map) sync hash and data

        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        wallet_changed = False
        if data is not None:
            added_accounts = wallet.merge(self.wallet_manager, password, data)
            if added_accounts and self.ledger.network.is_connected:
                if blocking:
                    await asyncio.wait([
                        a.ledger.subscribe_account(a) for a in added_accounts
                    ])
                else:
                    for new_account in added_accounts:
                        asyncio.create_task(self.ledger.subscribe_account(new_account))
            wallet_changed = True
        if wallet.preferences.get(ENCRYPT_ON_DISK, False) and password != wallet.encryption_password:
            wallet.encryption_password = password
            wallet_changed = True
        if wallet_changed:
            wallet.save()
        encrypted = wallet.pack(password)
        return {
            'hash': self.jsonrpc_sync_hash(wallet_id),
            'data': encrypted.decode()
        }
