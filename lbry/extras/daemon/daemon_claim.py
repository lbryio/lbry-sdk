#!/usr/bin/env python3
"""
Basic class with claim methods for the Daemon class (JSON-RPC server).
"""
from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.daemon_meta import DEFAULT_PAGE_SIZE
from lbry.extras.daemon.components import WALLET_COMPONENT
from lbry.wallet.constants import CLAIM_TYPE_NAMES


class Daemon_claim(metaclass=JSONRPCServerType):
    @requires(WALLET_COMPONENT)
    def jsonrpc_claim_list(self, claim_type=None, **kwargs):
        """
        List my stream and channel claims.

        Usage:
            claim_list [--claim_type=<claim_type>...] [--claim_id=<claim_id>...] [--name=<name>...] [--is_spent]
                       [--channel_id=<channel_id>...] [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                       [--has_source | --has_no_source] [--page=<page>] [--page_size=<page_size>]
                       [--resolve] [--order_by=<order_by>] [--no_totals] [--include_received_tips]

        Options:
            --claim_type=<claim_type>  : (str or list) claim type: channel, stream, repost, collection
            --claim_id=<claim_id>      : (str or list) claim id
            --channel_id=<channel_id>  : (str or list) streams in this channel
            --name=<name>              : (str or list) claim name
            --is_spent                 : (bool) shows previous claim updates and abandons
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --has_source               : (bool) list claims containing a source field
            --has_no_source            : (bool) list claims not containing a source field
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination
            --resolve                  : (bool) resolves each claim to provide additional metadata
            --order_by=<order_by>      : (str) field to order by: 'name', 'height', 'amount'
            --no_totals                : (bool) do not calculate the total number of pages and items in result set
                                                (significant performance boost)
            --include_received_tips    : (bool) calculate the amount of tips received for claim outputs

        Returns: {Paginated[Output]}
        """
        kwargs['type'] = claim_type or CLAIM_TYPE_NAMES
        if not kwargs.get('is_spent', False):
            kwargs['is_not_spent'] = True
        return self.jsonrpc_txo_list(**kwargs)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_claim_search(self, **kwargs):
        """
        Search for stream and channel claims on the blockchain.

        Arguments marked with "supports equality constraints" allow prepending the
        value with an equality constraint such as '>', '>=', '<' and '<='
        eg. --height=">400000" would limit results to only claims above 400k block height.

        Usage:
            claim_search [<name> | --name=<name>] [--text=<text>] [--txid=<txid>] [--nout=<nout>]
                         [--claim_id=<claim_id> | --claim_ids=<claim_ids>...]
                         [--channel=<channel> |
                             [[--channel_ids=<channel_ids>...] [--not_channel_ids=<not_channel_ids>...]]]
                         [--has_channel_signature] [--valid_channel_signature | --invalid_channel_signature]
                         [--limit_claims_per_channel=<limit_claims_per_channel>]
                         [--is_controlling] [--release_time=<release_time>] [--public_key_id=<public_key_id>]
                         [--timestamp=<timestamp>] [--creation_timestamp=<creation_timestamp>]
                         [--height=<height>] [--creation_height=<creation_height>]
                         [--activation_height=<activation_height>] [--expiration_height=<expiration_height>]
                         [--amount=<amount>] [--effective_amount=<effective_amount>]
                         [--support_amount=<support_amount>] [--trending_group=<trending_group>]
                         [--trending_mixed=<trending_mixed>] [--trending_local=<trending_local>]
                         [--trending_global=<trending_global]
                         [--reposted_claim_id=<reposted_claim_id>] [--reposted=<reposted>]
                         [--claim_type=<claim_type>] [--stream_types=<stream_types>...] [--media_types=<media_types>...]
                         [--fee_currency=<fee_currency>] [--fee_amount=<fee_amount>]
                         [--duration=<duration>]
                         [--any_tags=<any_tags>...] [--all_tags=<all_tags>...] [--not_tags=<not_tags>...]
                         [--any_languages=<any_languages>...] [--all_languages=<all_languages>...]
                         [--not_languages=<not_languages>...]
                         [--any_locations=<any_locations>...] [--all_locations=<all_locations>...]
                         [--not_locations=<not_locations>...]
                         [--order_by=<order_by>...] [--no_totals] [--page=<page>] [--page_size=<page_size>]
                         [--wallet_id=<wallet_id>] [--include_purchase_receipt] [--include_is_my_output]
                         [--remove_duplicates] [--has_source | --has_no_source]
                         [--new_sdk_server=<new_sdk_server>]

        Options:
            --name=<name>                   : (str) claim name (normalized)
            --text=<text>                   : (str) full text search
            --claim_id=<claim_id>           : (str) full or partial claim id
            --claim_ids=<claim_ids>         : (list) list of full claim ids
            --txid=<txid>                   : (str) transaction id
            --nout=<nout>                   : (str) position in the transaction
            --channel=<channel>             : (str) claims signed by this channel (argument is
                                                    a URL which automatically gets resolved),
                                                    see --channel_ids if you need to filter by
                                                    multiple channels at the same time,
                                                    includes claims with invalid signatures,
                                                    use in conjunction with --valid_channel_signature
            --channel_ids=<channel_ids>     : (list) claims signed by any of these channels
                                                    (arguments must be claim ids of the channels),
                                                    includes claims with invalid signatures,
                                                    implies --has_channel_signature,
                                                    use in conjunction with --valid_channel_signature
            --not_channel_ids=<not_channel_ids>: (list) exclude claims signed by any of these channels
                                                    (arguments must be claim ids of the channels)
            --has_channel_signature         : (bool) claims with a channel signature (valid or invalid)
            --valid_channel_signature       : (bool) claims with a valid channel signature or no signature,
                                                     use in conjunction with --has_channel_signature to
                                                     only get claims with valid signatures
            --invalid_channel_signature     : (bool) claims with invalid channel signature or no signature,
                                                     use in conjunction with --has_channel_signature to
                                                     only get claims with invalid signatures
            --limit_claims_per_channel=<limit_claims_per_channel>: (int) only return up to the specified
                                                                         number of claims per channel
            --is_controlling                : (bool) winning claims of their respective name
            --public_key_id=<public_key_id> : (str) only return channels having this public key id, this is
                                                    the same key as used in the wallet file to map
                                                    channel certificate private keys: {'public_key_id': 'private key'}
            --height=<height>               : (int) last updated block height (supports equality constraints)
            --timestamp=<timestamp>         : (int) last updated timestamp (supports equality constraints)
            --creation_height=<creation_height>      : (int) created at block height (supports equality constraints)
            --creation_timestamp=<creation_timestamp>: (int) created at timestamp (supports equality constraints)
            --activation_height=<activation_height>  : (int) height at which claim starts competing for name
                                                             (supports equality constraints)
            --expiration_height=<expiration_height>  : (int) height at which claim will expire
                                                             (supports equality constraints)
            --release_time=<release_time>   : (int) limit to claims self-described as having been
                                                    released to the public on or after this UTC
                                                    timestamp, when claim does not provide
                                                    a release time the publish time is used instead
                                                    (supports equality constraints)
            --amount=<amount>               : (int) limit by claim value (supports equality constraints)
            --support_amount=<support_amount>: (int) limit by supports and tips received (supports
                                                    equality constraints)
            --effective_amount=<effective_amount>: (int) limit by total value (initial claim value plus
                                                     all tips and supports received), this amount is
                                                     blank until claim has reached activation height
                                                     (supports equality constraints)
            --trending_group=<trending_group>: (int) group numbers 1 through 4 representing the
                                                    trending groups of the content: 4 means
                                                    content is trending globally and independently,
                                                    3 means content is not trending globally but is
                                                    trending independently (locally), 2 means it is
                                                    trending globally but not independently and 1
                                                    means it's not trending globally or locally
                                                    (supports equality constraints)
            --trending_mixed=<trending_mixed>: (int) trending amount taken from the global or local
                                                    value depending on the trending group:
                                                    4 - global value, 3 - local value, 2 - global
                                                    value, 1 - local value (supports equality
                                                    constraints)
            --trending_local=<trending_local>: (int) trending value calculated relative only to
                                                    the individual contents past history (supports
                                                    equality constraints)
            --trending_global=<trending_global>: (int) trending value calculated relative to all
                                                    trending content globally (supports
                                                    equality constraints)
            --reposted_claim_id=<reposted_claim_id>: (str) all reposts of the specified original claim id
            --reposted=<reposted>           : (int) claims reposted this many times (supports
                                                    equality constraints)
            --claim_type=<claim_type>       : (str) filter by 'channel', 'stream', 'repost' or 'collection'
            --stream_types=<stream_types>   : (list) filter by 'video', 'image', 'document', etc
            --media_types=<media_types>     : (list) filter by 'video/mp4', 'image/png', etc
            --fee_currency=<fee_currency>   : (string) specify fee currency: LBC, BTC, USD
            --fee_amount=<fee_amount>       : (decimal) content download fee (supports equality constraints)
            --duration=<duration>           : (int) duration of video or audio in seconds
                                                     (supports equality constraints)
            --any_tags=<any_tags>           : (list) find claims containing any of the tags
            --all_tags=<all_tags>           : (list) find claims containing every tag
            --not_tags=<not_tags>           : (list) find claims not containing any of these tags
            --any_languages=<any_languages> : (list) find claims containing any of the languages
            --all_languages=<all_languages> : (list) find claims containing every language
            --not_languages=<not_languages> : (list) find claims not containing any of these languages
            --any_locations=<any_locations> : (list) find claims containing any of the locations
            --all_locations=<all_locations> : (list) find claims containing every location
            --not_locations=<not_locations> : (list) find claims not containing any of these locations
            --page=<page>                   : (int) page to return during paginating
            --page_size=<page_size>         : (int) number of items on page during pagination
            --order_by=<order_by>           : (list) field to order by, default is descending order, to do an
                                                    ascending order prepend ^ to the field name, eg. '^amount'
                                                    available fields: 'name', 'height', 'release_time',
                                                    'publish_time', 'amount', 'effective_amount',
                                                    'support_amount', 'trending_group', 'trending_mixed',
                                                    'trending_local', 'trending_global', 'activation_height'
            --no_totals                     : (bool) do not calculate the total number of pages and items in result set
                                                     (significant performance boost)
            --wallet_id=<wallet_id>         : (str) wallet to check for claim purchase receipts
            --include_purchase_receipt      : (bool) lookup and include a receipt if this wallet
                                                     has purchased the claim
            --include_is_my_output          : (bool) lookup and include a boolean indicating
                                                     if claim being resolved is yours
            --remove_duplicates             : (bool) removes duplicated content from search by picking either the
                                                     original claim or the oldest matching repost
            --has_source                    : (bool) find claims containing a source field
            --has_no_source                 : (bool) find claims not containing a source field
           --new_sdk_server=<new_sdk_server> : (str) URL of the new SDK server (EXPERIMENTAL)

        Returns: {Paginated[Output]}
        """
        wallet = self.wallet_manager.get_wallet_or_default(kwargs.pop('wallet_id', None))
        if ("claim_ids" in kwargs and not kwargs["claim_ids"]
                and "claim_id" in kwargs and kwargs["claim_id"]):
            kwargs.pop("claim_ids")
        if {'claim_id', 'claim_ids'}.issubset(kwargs):
            raise ValueError("Only 'claim_id' or 'claim_ids' is allowed, not both.")
        if kwargs.pop('valid_channel_signature', False):
            kwargs['signature_valid'] = 1
        if kwargs.pop('invalid_channel_signature', False):
            kwargs['signature_valid'] = 0
        if 'has_no_source' in kwargs:
            kwargs['has_source'] = not kwargs.pop('has_no_source')
        page_num, page_size = abs(kwargs.pop('page', 1)), min(abs(kwargs.pop('page_size', DEFAULT_PAGE_SIZE)), 50)
        kwargs.update({'offset': page_size * (page_num - 1), 'limit': page_size})
        txos, blocked, _, total = await self.ledger.claim_search(wallet.accounts, **kwargs)
        result = {
            "items": txos,
            "blocked": blocked,
            "page": page_num,
            "page_size": page_size
        }
        if not kwargs.pop('no_totals', False):
            result['total_pages'] = int((total + (page_size - 1)) / page_size)
            result['total_items'] = total
        return result
