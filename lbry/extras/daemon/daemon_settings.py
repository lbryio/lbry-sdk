#!/usr/bin/env python3
"""
Basic class with settings methods for the Daemon class (JSON-RPC server).
"""
import json

from lbry.conf import Setting, NOT_SET
from lbry.extras.daemon.daemon_meta import JSONRPCServerType


class Daemon_settings(metaclass=JSONRPCServerType):
    def jsonrpc_settings_get(self):
        """
        Get daemon settings

        Usage:
            settings_get

        Options:
            None

        Returns:
            (dict) Dictionary of daemon settings
            See ADJUSTABLE_SETTINGS in lbry/conf.py for full list of settings
        """
        return self.conf.settings_dict

    def jsonrpc_settings_set(self, key, value):
        """
        Set daemon settings

        Usage:
            settings_set (<key>) (<value>)

        Options:
            None

        Returns:
            (dict) Updated dictionary of daemon settings
        """
        with self.conf.update_config() as c:
            if value and isinstance(value, str) and value[0] in ('[', '{'):
                value = json.loads(value)
            attr: Setting = getattr(type(c), key)
            cleaned = attr.deserialize(value)
            setattr(c, key, cleaned)
        return {key: cleaned}

    def jsonrpc_settings_clear(self, key):
        """
        Clear daemon settings

        Usage:
            settings_clear (<key>)

        Options:
            None

        Returns:
            (dict) Updated dictionary of daemon settings
        """
        with self.conf.update_config() as c:
            setattr(c, key, NOT_SET)
        return {key: self.conf.settings_dict[key]}

    def jsonrpc_preference_get(self, key=None, wallet_id=None):
        """
        Get preference value for key or all values if not key is passed in.

        Usage:
            preference_get [<key>] [--wallet_id=<wallet_id>]

        Options:
            --key=<key> : (str) key associated with value
            --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet

        Returns:
            (dict) Dictionary of preference(s)
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        if key:
            if key in wallet.preferences:
                return {key: wallet.preferences[key]}
            return
        return wallet.preferences.to_dict_without_ts()

    def jsonrpc_preference_set(self, key, value, wallet_id=None):
        """
        Set preferences

        Usage:
            preference_set (<key>) (<value>) [--wallet_id=<wallet_id>]

        Options:
            --key=<key> : (str) key associated with value
            --value=<key> : (str) key associated with value
            --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet

        Returns:
            (dict) Dictionary with key/value of new preference
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        if value and isinstance(value, str) and value[0] in ('[', '{'):
            value = json.loads(value)
        wallet.preferences[key] = value
        wallet.save()
        return {key: value}
