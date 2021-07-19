#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Basic class with comment methods for the Daemon class (JSON-RPC server).
"""
import typing

from lbry.wallet import Output
from lbry.extras.daemon import comment_client
from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.components import WALLET_COMPONENT


class Daemon_comment(metaclass=JSONRPCServerType):
    async def jsonrpc_comment_list(self, claim_id, parent_id=None, page=1, page_size=50,
                                   include_replies=False, skip_validation=False,
                                   is_channel_signature_valid=False, hidden=False, visible=False):
        """
        List comments associated with a claim.

        Usage:
            comment_list    (<claim_id> | --claim_id=<claim_id>)
                            [(--page=<page> --page_size=<page_size>)]
                            [--parent_id=<parent_id>] [--include_replies]
                            [--skip_validation] [--is_channel_signature_valid]
                            [--visible | --hidden]

        Options:
            --claim_id=<claim_id>           : (str) The claim on which the comment will be made on
            --parent_id=<parent_id>         : (str) CommentId of a specific thread you'd like to see
            --page=<page>                   : (int) The page you'd like to see in the comment list.
            --page_size=<page_size>         : (int) The amount of comments that you'd like to retrieve
            --skip_validation               : (bool) Skip resolving comments to validate channel names
            --include_replies               : (bool) Whether or not you want to include replies in list
            --is_channel_signature_valid    : (bool) Only include comments with valid signatures.
                                              [Warning: Paginated total size will not change, even
                                               if list reduces]
            --visible                       : (bool) Select only Visible Comments
            --hidden                        : (bool) Select only Hidden Comments

        Returns:
            (dict)  Containing the list, and information about the paginated content:
            {
                "page": "Page number of the current items.",
                "page_size": "Number of items to show on a page.",
                "total_pages": "Total number of pages.",
                "total_items": "Total number of items.",
                "items": "A List of dict objects representing comments."
                [
                    {
                        "comment":      (str) The actual string as inputted by the user,
                        "comment_id":   (str) The Comment's unique identifier,
                        "channel_name": (str) Name of the channel this was posted under, prepended with a '@',
                        "channel_id":   (str) The Channel Claim ID that this comment was posted under,
                        "signature":    (str) The signature of the comment,
                        "channel_url":  (str) Channel's URI in the ClaimTrie,
                        "parent_id":    (str) Comment this is replying to, (None) if this is the root,
                        "timestamp":    (int) The time at which comment was entered into the server at, in nanoseconds.
                    },
                    ...
                ]
            }
        """
        if hidden ^ visible:
            result = await comment_client.jsonrpc_post(
                self.conf.comment_server,
                'comment.List',
                claim_id=claim_id,
                visible=visible,
                hidden=hidden,
                page=page,
                page_size=page_size
            )
        else:
            result = await comment_client.jsonrpc_post(
                self.conf.comment_server,
                'comment.List',
                claim_id=claim_id,
                parent_id=parent_id,
                page=page,
                page_size=page_size,
                top_level=not include_replies
            )
        if not skip_validation:
            for comment in result.get('items', []):
                channel_url = comment.get('channel_url')
                if not channel_url:
                    continue
                resolve_response = await self.resolve([], [channel_url])
                if isinstance(resolve_response[channel_url], Output):
                    comment['is_channel_signature_valid'] = comment_client.is_comment_signed_by_channel(
                        comment, resolve_response[channel_url]
                    )
                else:
                    comment['is_channel_signature_valid'] = False
            if is_channel_signature_valid:
                result['items'] = [
                    c for c in result.get('items', []) if c.get('is_channel_signature_valid', False)
                ]
        return result

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_create(self, comment, claim_id=None, parent_id=None, channel_account_id=None,
                                     channel_name=None, channel_id=None, wallet_id=None):
        """
        Create and associate a comment with a claim using your channel identity.

        Usage:
            comment_create  (<comment> | --comment=<comment>)
                            (<claim_id> | --claim_id=<claim_id>) [--parent_id=<parent_id>]
                            (--channel_id=<channel_id> | --channel_name=<channel_name>)
                            [--channel_account_id=<channel_account_id>...] [--wallet_id=<wallet_id>]

        Options:
            --comment=<comment>                         : (str) Comment to be made, should be at most 2000 characters.
            --claim_id=<claim_id>                       : (str) The ID of the claim to comment on
            --parent_id=<parent_id>                     : (str) The ID of a comment to make a response to
            --channel_id=<channel_id>                   : (str) The ID of the channel you want to post under
            --channel_name=<channel_name>               : (str) The channel you want to post as, prepend with a '@'
            --channel_account_id=<channel_account_id>   : (str) one or more account ids for accounts to look in
                                                          for channel certificates, defaults to all accounts
            --wallet_id=<wallet_id>                     : (str) restrict operation to specific wallet

        Returns:
            (dict) Comment object if successfully made, (None) otherwise
            {
                "comment":      (str) The actual string as inputted by the user,
                "comment_id":   (str) The Comment's unique identifier,
                "claim_id":     (str) The claim commented on,
                "channel_name": (str) Name of the channel this was posted under, prepended with a '@',
                "channel_id":   (str) The Channel Claim ID that this comment was posted under,
                "is_pinned":    (boolean) Channel owner has pinned this comment,
                "signature":    (str) The signature of the comment,
                "signing_ts":   (str) The timestamp used to sign the comment,
                "channel_url":  (str) Channel's URI in the ClaimTrie,
                "parent_id":    (str) Comment this is replying to, (None) if this is the root,
                "timestamp":    (int) The time at which comment was entered into the server at, in nanoseconds.
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        channel = await self.get_channel_or_error(
            wallet, channel_account_id, channel_id, channel_name, for_signing=True
        )

        comment_body = {
            'comment': comment.strip(),
            'claim_id': claim_id,
            'parent_id': parent_id,
            'channel_id': channel.claim_id,
            'channel_name': channel.claim_name,
        }
        comment_client.sign_comment(comment_body, channel)

        response = await comment_client.jsonrpc_post(self.conf.comment_server, 'comment.Create', comment_body)
        response.update({
            'is_claim_signature_valid': comment_client.is_comment_signed_by_channel(response, channel)
        })
        return response

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_update(self, comment, comment_id, wallet_id=None):
        """
        Edit a comment published as one of your channels.

        Usage:
            comment_update (<comment> | --comment=<comment>)
                         (<comment_id> | --comment_id=<comment_id>)
                         [--wallet_id=<wallet_id>]

        Options:
            --comment=<comment>         : (str) New comment replacing the old one
            --comment_id=<comment_id>   : (str) Hash identifying the comment to edit
            --wallet_id=<wallet_id      : (str) restrict operation to specific wallet

        Returns:
            (dict) Comment object if edit was successful, (None) otherwise
            {
                "comment":      (str) The actual string as inputted by the user,
                "comment_id":   (str) The Comment's unique identifier,
                "claim_id":     (str) The claim commented on,
                "channel_name": (str) Name of the channel this was posted under, prepended with a '@',
                "channel_id":   (str) The Channel Claim ID that this comment was posted under,
                "signature":    (str) The signature of the comment,
                "signing_ts":   (str) Timestamp used to sign the most recent signature,
                "channel_url":  (str) Channel's URI in the ClaimTrie,
                "is_pinned":    (boolean) Channel owner has pinned this comment,
                "parent_id":    (str) Comment this is replying to, (None) if this is the root,
                "timestamp":    (int) The time at which comment was entered into the server at, in nanoseconds.
            }
        """
        channel = await comment_client.jsonrpc_post(
            self.conf.comment_server,
            'comment.GetChannelFromCommentID',
            comment_id=comment_id
        )
        if 'error' in channel:
            raise ValueError(channel['error'])

        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        # channel = await self.get_channel_or_none(wallet, None, **channel)
        channel_claim = await self.get_channel_or_error(wallet, [], **channel)
        edited_comment = {
            'comment_id': comment_id,
            'comment': comment,
            'channel_id': channel_claim.claim_id,
            'channel_name': channel_claim.claim_name
        }
        comment_client.sign_comment(edited_comment, channel_claim)
        return await comment_client.jsonrpc_post(
            self.conf.comment_server, 'comment.Edit', edited_comment
        )

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_abandon(self, comment_id, wallet_id=None):
        """
        Abandon a comment published under your channel identity.

        Usage:
            comment_abandon  (<comment_id> | --comment_id=<comment_id>) [--wallet_id=<wallet_id>]

        Options:
            --comment_id=<comment_id>   : (str) The ID of the comment to be abandoned.
            --wallet_id=<wallet_id      : (str) restrict operation to specific wallet

        Returns:
            (dict) Object with the `comment_id` passed in as the key, and a flag indicating if it was abandoned
            {
                <comment_id> (str): {
                    "abandoned": (bool)
                }
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        abandon_comment_body = {'comment_id': comment_id}
        channel = await comment_client.jsonrpc_post(
            self.conf.comment_server, 'comment.GetChannelFromCommentID', comment_id=comment_id
        )
        if 'error' in channel:
            return {comment_id: {'abandoned': False}}
        channel = await self.get_channel_or_none(wallet, None, **channel)
        abandon_comment_body.update({
            'channel_id': channel.claim_id,
            'channel_name': channel.claim_name,
        })
        comment_client.sign_comment(abandon_comment_body, channel, sign_comment_id=True)
        return await comment_client.jsonrpc_post(self.conf.comment_server, 'comment.Abandon', abandon_comment_body)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_hide(self, comment_ids: typing.Union[str, list], wallet_id=None):
        """
        Hide a comment published to a claim you control.

        Usage:
            comment_hide  <comment_ids>... [--wallet_id=<wallet_id>]

        Options:
            --comment_ids=<comment_ids>  : (str, list) one or more comment_id to hide.
            --wallet_id=<wallet_id>      : (str) restrict operation to specific wallet

        Returns: lists containing the ids comments that are hidden and visible.

            {
                "hidden":   (list) IDs of hidden comments.
                "visible":  (list) IDs of visible comments.
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)

        if isinstance(comment_ids, str):
            comment_ids = [comment_ids]

        comments = await comment_client.jsonrpc_post(
            self.conf.comment_server, 'get_comments_by_id', comment_ids=comment_ids
        )
        comments = comments['items']
        claim_ids = {comment['claim_id'] for comment in comments}
        claims = {cid: await self.ledger.get_claim_by_claim_id(wallet.accounts, claim_id=cid) for cid in claim_ids}
        pieces = []
        for comment in comments:
            claim = claims.get(comment['claim_id'])
            if claim:
                channel = await self.get_channel_or_none(
                    wallet,
                    account_ids=[],
                    channel_id=claim.channel.claim_id,
                    channel_name=claim.channel.claim_name,
                    for_signing=True
                )
                piece = {'comment_id': comment['comment_id']}
                comment_client.sign_comment(piece, channel, sign_comment_id=True)
                pieces.append(piece)
        return await comment_client.jsonrpc_post(self.conf.comment_server, 'comment.Hide', pieces=pieces)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_pin(self, comment_id=None, channel_id=None, channel_name=None,
                                  channel_account_id=None, remove=False, wallet_id=None):
        """
        Pin a comment published to a claim you control.

        Usage:
            comment_pin     (<comment_id> | --comment_id=<comment_id>)
                            (--channel_id=<channel_id>)
                            (--channel_name=<channel_name>)
                            [--remove]
                            [--channel_account_id=<channel_account_id>...] [--wallet_id=<wallet_id>]

        Options:
            --comment_id=<comment_id>   : (str) Hash identifying the comment to pin
            --channel_id=<claim_id>                     : (str) The ID of channel owning the commented claim
            --channel_name=<claim_name>                 : (str) The name of channel owning the commented claim
            --remove                                    : (bool) remove the pin
            --channel_account_id=<channel_account_id>   : (str) one or more account ids for accounts to look in
            --wallet_id=<wallet_id                      : (str) restrict operation to specific wallet

        Returns: lists containing the ids comments that are hidden and visible.

            {
                "hidden":   (list) IDs of hidden comments.
                "visible":  (list) IDs of visible comments.
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        channel = await self.get_channel_or_error(
            wallet, channel_account_id, channel_id, channel_name, for_signing=True
        )
        comment_pin_args = {
            'comment_id': comment_id,
            'channel_name': channel_name,
            'channel_id': channel_id,
            'remove': remove,
        }
        comment_client.sign_comment(comment_pin_args, channel, sign_comment_id=True)
        return await comment_client.jsonrpc_post(self.conf.comment_server, 'comment.Pin', comment_pin_args)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_react(
            self, comment_ids, channel_name=None, channel_id=None,
            channel_account_id=None, remove=False, clear_types=None, react_type=None, wallet_id=None):
        """
        Create and associate a reaction emoji with a comment using your channel identity.

        Usage:
            comment_react   (--comment_ids=<comment_ids>)
                            (--channel_id=<channel_id>)
                            (--channel_name=<channel_name>)
                            (--react_type=<react_type>)
                            [(--remove) | (--clear_types=<clear_types>)]
                            [--channel_account_id=<channel_account_id>...] [--wallet_id=<wallet_id>]

        Options:
            --comment_ids=<comment_ids>                 : (str) one or more comment id reacted to, comma delimited
            --channel_id=<claim_id>                     : (str) The ID of channel reacting
            --channel_name=<claim_name>                 : (str) The name of the channel reacting
            --wallet_id=<wallet_id>                     : (str) restrict operation to specific wallet
            --channel_account_id=<channel_account_id>   : (str) one or more account ids for accounts to look in
            --react_type=<react_type>                   : (str) name of reaction type
            --remove                                    : (bool) remove specified react_type
            --clear_types=<clear_types>                 : (str) types to clear when adding another type


        Returns:
            (dict) Reaction object if successfully made, (None) otherwise
            {
            "Reactions": {
                <comment_id>: {
                    <reaction_type>: (int) Count for this reaction
                    ...
                }
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        channel = await self.get_channel_or_error(
            wallet, channel_account_id, channel_id, channel_name, for_signing=True
        )

        react_body = {
            'comment_ids': comment_ids,
            'channel_id': channel_id,
            'channel_name': channel.claim_name,
            'type': react_type,
            'remove': remove,
            'clear_types': clear_types,
        }
        comment_client.sign_reaction(react_body, channel)

        response = await comment_client.jsonrpc_post(self.conf.comment_server, 'reaction.React', react_body)

        return response

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_react_list(
            self, comment_ids, channel_name=None, channel_id=None,
            channel_account_id=None, react_types=None, wallet_id=None):
        """
        List reactions emoji with a claim using your channel identity.

        Usage:
            comment_react_list  (--comment_ids=<comment_ids>)
                                [(--channel_id=<channel_id>)(--channel_name=<channel_name>)]
                                [--react_types=<react_types>]

        Options:
            --comment_ids=<comment_ids>                 : (str) The comment ids reacted to, comma delimited
            --channel_id=<claim_id>                     : (str) The ID of channel reacting
            --channel_name=<claim_name>                 : (str) The name of the channel reacting
            --wallet_id=<wallet_id>                     : (str) restrict operation to specific wallet
            --react_types=<react_type>                   : (str) comma delimited reaction types

        Returns:
            (dict) Comment object if successfully made, (None) otherwise
            {
                "my_reactions": {
                    <comment_id>: {
                    <reaction_type>: (int) Count for this reaction type
                    ...
                    }
                }
                "other_reactions": {
                    <comment_id>: {
                    <reaction_type>: (int) Count for this reaction type
                    ...
                    }
                }
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        react_list_body = {
            'comment_ids': comment_ids,
        }
        if channel_id:
            channel = await self.get_channel_or_error(
                wallet, channel_account_id, channel_id, channel_name, for_signing=True
            )
            react_list_body['channel_id'] = channel_id
            react_list_body['channel_name'] = channel.claim_name

        if react_types:
            react_list_body['types'] = react_types
        if channel_id:
            comment_client.sign_reaction(react_list_body, channel)
        response = await comment_client.jsonrpc_post(self.conf.comment_server, 'reaction.List', react_list_body)
        return response
