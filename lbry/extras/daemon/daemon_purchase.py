#!/usr/bin/env python3
"""
Basic class with purchase methods for the Daemon class (JSON-RPC server).
"""
from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.daemon_meta import paginate_rows
from lbry.extras.daemon.components import WALLET_COMPONENT
from lbry.wallet import Output


class Daemon_purchase(metaclass=JSONRPCServerType):
    @requires(WALLET_COMPONENT)
    def jsonrpc_purchase_list(
            self, claim_id=None, resolve=False, account_id=None, wallet_id=None, page=None, page_size=None):
        """
        List my claim purchases.

        Usage:
            purchase_list [<claim_id> | --claim_id=<claim_id>] [--resolve]
                          [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                          [--page=<page>] [--page_size=<page_size>]

        Options:
            --claim_id=<claim_id>      : (str) purchases for specific claim
            --resolve                  : (str) include resolved claim information
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns: {Paginated[Output]}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        constraints = {
            "wallet": wallet,
            "accounts": [wallet.get_account_or_error(account_id)] if account_id else wallet.accounts,
            "resolve": resolve,
        }
        if claim_id:
            constraints["purchased_claim_id"] = claim_id
        return paginate_rows(
            self.ledger.get_purchases,
            self.ledger.get_purchase_count,
            page, page_size, **constraints
        )

    @requires(WALLET_COMPONENT)
    async def jsonrpc_purchase_create(
            self, claim_id=None, url=None, wallet_id=None, funding_account_ids=None,
            allow_duplicate_purchase=False, override_max_key_fee=False, preview=False, blocking=False):
        """
        Purchase a claim.

        Usage:
            purchase_create (--claim_id=<claim_id> | --url=<url>) [--wallet_id=<wallet_id>]
                    [--funding_account_ids=<funding_account_ids>...]
                    [--allow_duplicate_purchase] [--override_max_key_fee] [--preview] [--blocking]

        Options:
            --claim_id=<claim_id>          : (str) claim id of claim to purchase
            --url=<url>                    : (str) lookup claim to purchase by url
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
          --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --allow_duplicate_purchase     : (bool) allow purchasing claim_id you already own
            --override_max_key_fee         : (bool) ignore max key fee for this purchase
            --preview                      : (bool) do not broadcast the transaction
            --blocking                     : (bool) wait until transaction is in mempool

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        accounts = wallet.get_accounts_or_all(funding_account_ids)
        txo = None
        if claim_id:
            txo = await self.ledger.get_claim_by_claim_id(accounts, claim_id, include_purchase_receipt=True)
            if not isinstance(txo, Output) or not txo.is_claim:
                raise Exception(f"Could not find claim with claim_id '{claim_id}'. ")
        elif url:
            txo = (await self.ledger.resolve(accounts, [url], include_purchase_receipt=True))[url]
            if not isinstance(txo, Output) or not txo.is_claim:
                raise Exception(f"Could not find claim with url '{url}'. ")
        else:
            raise Exception(f"Missing argument claim_id or url. ")
        if not allow_duplicate_purchase and txo.purchase_receipt:
            raise Exception(
                f"You already have a purchase for claim_id '{claim_id}'. "
                f"Use --allow-duplicate-purchase flag to override."
            )
        claim = txo.claim
        if not claim.is_stream or not claim.stream.has_fee:
            raise Exception(f"Claim '{claim_id}' does not have a purchase price.")
        tx = await self.wallet_manager.create_purchase_transaction(
            accounts, txo, self.exchange_rate_manager, override_max_key_fee
        )
        if not preview:
            await self.broadcast_or_release(tx, blocking)
        else:
            await self.ledger.release_tx(tx)
        return tx
