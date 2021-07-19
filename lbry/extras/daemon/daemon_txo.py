#!/usr/bin/env python3
"""
Basic class with txo methods for the Daemon class (JSON-RPC server).
"""
from functools import partial

from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.daemon_meta import paginate_rows
from lbry.extras.daemon.components import WALLET_COMPONENT
from lbry.wallet import database, Input, Transaction
from lbry.wallet.constants import TXO_TYPES
from lbry.wallet.dewies import dewies_to_lbc


class Daemon_txo(metaclass=JSONRPCServerType):
    @staticmethod
    def _constrain_txo_from_kwargs(
            constraints, type=None, txid=None,  # pylint: disable=redefined-builtin
            claim_id=None, channel_id=None, not_channel_id=None,
            name=None, reposted_claim_id=None,
            is_spent=False, is_not_spent=False,
            has_source=None, has_no_source=None,
            is_my_input_or_output=None, exclude_internal_transfers=False,
            is_my_output=None, is_not_my_output=None,
            is_my_input=None, is_not_my_input=None):
        if is_spent:
            constraints['is_spent'] = True
        elif is_not_spent:
            constraints['is_spent'] = False
        if has_source:
            constraints['has_source'] = True
        elif has_no_source:
            constraints['has_source'] = False
        constraints['exclude_internal_transfers'] = exclude_internal_transfers
        if is_my_input_or_output is True:
            constraints['is_my_input_or_output'] = True
        else:
            if is_my_input is True:
                constraints['is_my_input'] = True
            elif is_not_my_input is True:
                constraints['is_my_input'] = False
            if is_my_output is True:
                constraints['is_my_output'] = True
            elif is_not_my_output is True:
                constraints['is_my_output'] = False
        database.constrain_single_or_list(constraints, 'txo_type', type, lambda x: TXO_TYPES[x])
        database.constrain_single_or_list(constraints, 'channel_id', channel_id)
        database.constrain_single_or_list(constraints, 'channel_id', not_channel_id, negate=True)
        database.constrain_single_or_list(constraints, 'claim_id', claim_id)
        database.constrain_single_or_list(constraints, 'claim_name', name)
        database.constrain_single_or_list(constraints, 'txid', txid)
        database.constrain_single_or_list(constraints, 'reposted_claim_id', reposted_claim_id)
        return constraints

    @requires(WALLET_COMPONENT)
    def jsonrpc_txo_list(
            self, account_id=None, wallet_id=None, page=None, page_size=None,
            resolve=False, order_by=None, no_totals=False, include_received_tips=False, **kwargs):
        """
        List my transaction outputs.

        Usage:
            txo_list [--account_id=<account_id>] [--type=<type>...] [--txid=<txid>...] [--claim_id=<claim_id>...]
                     [--channel_id=<channel_id>...] [--not_channel_id=<not_channel_id>...]
                     [--name=<name>...] [--is_spent | --is_not_spent]
                     [--is_my_input_or_output |
                         [[--is_my_output | --is_not_my_output] [--is_my_input | --is_not_my_input]]
                     ]
                     [--exclude_internal_transfers] [--include_received_tips]
                     [--wallet_id=<wallet_id>] [--page=<page>] [--page_size=<page_size>]
                     [--resolve] [--order_by=<order_by>][--no_totals]

        Options:
            --type=<type>              : (str or list) claim type: stream, channel, support,
                                         purchase, collection, repost, other
            --txid=<txid>              : (str or list) transaction id of outputs
            --claim_id=<claim_id>      : (str or list) claim id
            --channel_id=<channel_id>  : (str or list) claims in this channel
      --not_channel_id=<not_channel_id>: (str or list) claims not in this channel
            --name=<name>              : (str or list) claim name
            --is_spent                 : (bool) only show spent txos
            --is_not_spent             : (bool) only show not spent txos
            --is_my_input_or_output    : (bool) txos which have your inputs or your outputs,
                                                if using this flag the other related flags
                                                are ignored (--is_my_output, --is_my_input, etc)
            --is_my_output             : (bool) show outputs controlled by you
            --is_not_my_output         : (bool) show outputs not controlled by you
            --is_my_input              : (bool) show outputs created by you
            --is_not_my_input          : (bool) show outputs not created by you
           --exclude_internal_transfers: (bool) excludes any outputs that are exactly this combination:
                                                "--is_my_input --is_my_output --type=other"
                                                this allows to exclude "change" payments, this
                                                flag can be used in combination with any of the other flags
            --include_received_tips    : (bool) calculate the amount of tips received for claim outputs
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination
            --resolve                  : (bool) resolves each claim to provide additional metadata
            --order_by=<order_by>      : (str) field to order by: 'name', 'height', 'amount' and 'none'
            --no_totals                : (bool) do not calculate the total number of pages and items in result set
                                                (significant performance boost)

        Returns: {Paginated[Output]}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        if account_id:
            account = wallet.get_account_or_error(account_id)
            claims = account.get_txos
            claim_count = account.get_txo_count
        else:
            claims = partial(self.ledger.get_txos, wallet=wallet, accounts=wallet.accounts, read_only=True)
            claim_count = partial(self.ledger.get_txo_count, wallet=wallet, accounts=wallet.accounts, read_only=True)
        constraints = {
            'resolve': resolve,
            'include_is_spent': True,
            'include_is_my_input': True,
            'include_is_my_output': True,
            'include_received_tips': include_received_tips
        }
        if order_by is not None:
            if order_by == 'name':
                constraints['order_by'] = 'txo.claim_name'
            elif order_by in ('height', 'amount', 'none'):
                constraints['order_by'] = order_by
            else:
                raise ValueError(f"'{order_by}' is not a valid --order_by value.")
        self._constrain_txo_from_kwargs(constraints, **kwargs)
        return paginate_rows(claims, None if no_totals else claim_count, page, page_size, **constraints)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_txo_spend(
            self, account_id=None, wallet_id=None, batch_size=100,
            include_full_tx=False, preview=False, blocking=False, **kwargs):
        """
        Spend transaction outputs, batching into multiple transactions as necessary.

        Usage:
            txo_spend [--account_id=<account_id>] [--type=<type>...] [--txid=<txid>...] [--claim_id=<claim_id>...]
                      [--channel_id=<channel_id>...] [--not_channel_id=<not_channel_id>...]
                      [--name=<name>...] [--is_my_input | --is_not_my_input]
                      [--exclude_internal_transfers] [--wallet_id=<wallet_id>]
                      [--preview] [--blocking] [--batch_size=<batch_size>] [--include_full_tx]

        Options:
            --type=<type>              : (str or list) claim type: stream, channel, support,
                                         purchase, collection, repost, other
            --txid=<txid>              : (str or list) transaction id of outputs
            --claim_id=<claim_id>      : (str or list) claim id
            --channel_id=<channel_id>  : (str or list) claims in this channel
      --not_channel_id=<not_channel_id>: (str or list) claims not in this channel
            --name=<name>              : (str or list) claim name
            --is_my_input              : (bool) show outputs created by you
            --is_not_my_input          : (bool) show outputs not created by you
           --exclude_internal_transfers: (bool) excludes any outputs that are exactly this combination:
                                                "--is_my_input --is_my_output --type=other"
                                                this allows to exclude "change" payments, this
                                                flag can be used in combination with any of the other flags
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --preview                  : (bool) do not broadcast the transaction
            --blocking                 : (bool) wait until abandon is in mempool
            --batch_size=<batch_size>  : (int) number of txos to spend per transactions
            --include_full_tx          : (bool) include entire tx in output and not just the txid

        Returns: {List[Transaction]}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        accounts = [wallet.get_account_or_error(account_id)] if account_id else wallet.accounts
        txos = await self.ledger.get_txos(
            wallet=wallet, accounts=accounts, read_only=True,
            no_tx=True, no_channel_info=True,
            **self._constrain_txo_from_kwargs(
                {}, is_not_spent=True, is_my_output=True, **kwargs
            )
        )
        txs = []
        while txos:
            txs.append(
                await Transaction.create(
                    [Input.spend(txos.pop()) for _ in range(min(len(txos), batch_size))],
                    [], accounts, accounts[0]
                )
            )
        if not preview:
            for tx in txs:
                await self.broadcast_or_release(tx, blocking)
        if include_full_tx:
            return txs
        return [{'txid': tx.id} for tx in txs]

    @requires(WALLET_COMPONENT)
    def jsonrpc_txo_sum(self, account_id=None, wallet_id=None, **kwargs):
        """
        Sum of transaction outputs.

        Usage:
            txo_list [--account_id=<account_id>] [--type=<type>...] [--txid=<txid>...]
                     [--channel_id=<channel_id>...] [--not_channel_id=<not_channel_id>...]
                     [--claim_id=<claim_id>...] [--name=<name>...]
                     [--is_spent] [--is_not_spent]
                     [--is_my_input_or_output |
                         [[--is_my_output | --is_not_my_output] [--is_my_input | --is_not_my_input]]
                     ]
                     [--exclude_internal_transfers] [--wallet_id=<wallet_id>]

        Options:
            --type=<type>              : (str or list) claim type: stream, channel, support,
                                         purchase, collection, repost, other
            --txid=<txid>              : (str or list) transaction id of outputs
            --claim_id=<claim_id>      : (str or list) claim id
            --name=<name>              : (str or list) claim name
            --channel_id=<channel_id>  : (str or list) claims in this channel
      --not_channel_id=<not_channel_id>: (str or list) claims not in this channel
            --is_spent                 : (bool) only show spent txos
            --is_not_spent             : (bool) only show not spent txos
            --is_my_input_or_output    : (bool) txos which have your inputs or your outputs,
                                                if using this flag the other related flags
                                                are ignored (--is_my_output, --is_my_input, etc)
            --is_my_output             : (bool) show outputs controlled by you
            --is_not_my_output         : (bool) show outputs not controlled by you
            --is_my_input              : (bool) show outputs created by you
            --is_not_my_input          : (bool) show outputs not created by you
           --exclude_internal_transfers: (bool) excludes any outputs that are exactly this combination:
                                                "--is_my_input --is_my_output --type=other"
                                                this allows to exclude "change" payments, this
                                                flag can be used in combination with any of the other flags
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet

        Returns: int
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        return self.ledger.get_txo_sum(
            wallet=wallet, accounts=[wallet.get_account_or_error(account_id)] if account_id else wallet.accounts,
            read_only=True, **self._constrain_txo_from_kwargs({}, **kwargs)
        )

    @requires(WALLET_COMPONENT)
    async def jsonrpc_txo_plot(
            self, account_id=None, wallet_id=None,
            days_back=0, start_day=None, days_after=None, end_day=None, **kwargs):
        """
        Plot transaction output sum over days.

        Usage:
            txo_plot [--account_id=<account_id>] [--type=<type>...] [--txid=<txid>...]
                     [--claim_id=<claim_id>...] [--name=<name>...] [--is_spent] [--is_not_spent]
                     [--channel_id=<channel_id>...] [--not_channel_id=<not_channel_id>...]
                     [--is_my_input_or_output |
                         [[--is_my_output | --is_not_my_output] [--is_my_input | --is_not_my_input]]
                     ]
                     [--exclude_internal_transfers] [--wallet_id=<wallet_id>]
                     [--days_back=<days_back> |
                        [--start_day=<start_day> [--days_after=<days_after> | --end_day=<end_day>]]
                     ]

        Options:
            --type=<type>              : (str or list) claim type: stream, channel, support,
                                         purchase, collection, repost, other
            --txid=<txid>              : (str or list) transaction id of outputs
            --claim_id=<claim_id>      : (str or list) claim id
            --name=<name>              : (str or list) claim name
            --channel_id=<channel_id>  : (str or list) claims in this channel
      --not_channel_id=<not_channel_id>: (str or list) claims not in this channel
            --is_spent                 : (bool) only show spent txos
            --is_not_spent             : (bool) only show not spent txos
            --is_my_input_or_output    : (bool) txos which have your inputs or your outputs,
                                                if using this flag the other related flags
                                                are ignored (--is_my_output, --is_my_input, etc)
            --is_my_output             : (bool) show outputs controlled by you
            --is_not_my_output         : (bool) show outputs not controlled by you
            --is_my_input              : (bool) show outputs created by you
            --is_not_my_input          : (bool) show outputs not created by you
           --exclude_internal_transfers: (bool) excludes any outputs that are exactly this combination:
                                                "--is_my_input --is_my_output --type=other"
                                                this allows to exclude "change" payments, this
                                                flag can be used in combination with any of the other flags
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --days_back=<days_back>    : (int) number of days back from today
                                               (not compatible with --start_day, --days_after, --end_day)
            --start_day=<start_day>    : (date) start on specific date (YYYY-MM-DD)
                                               (instead of --days_back)
            --days_after=<days_after>  : (int) end number of days after --start_day
                                               (instead of --end_day)
            --end_day=<end_day>        : (date) end on specific date (YYYY-MM-DD)
                                               (instead of --days_after)

        Returns: List[Dict]
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        plot = await self.ledger.get_txo_plot(
            wallet=wallet, accounts=[wallet.get_account_or_error(account_id)] if account_id else wallet.accounts,
            read_only=True, days_back=days_back, start_day=start_day, days_after=days_after, end_day=end_day,
            **self._constrain_txo_from_kwargs({}, **kwargs)
        )
        for row in plot:
            row['total'] = dewies_to_lbc(row['total'])
        return plot
