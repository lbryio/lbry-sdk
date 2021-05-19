# Copyright (c) 2016, Neil Booth
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.


import re
import resource
from os import environ
from collections import namedtuple
from ipaddress import ip_address

from lbry.wallet.server.util import class_logger
from lbry.wallet.server.coin import Coin
import lbry.wallet.server.util as lib_util


NetIdentity = namedtuple('NetIdentity', 'host tcp_port ssl_port nick_suffix')


class Env:

    # Peer discovery
    PD_OFF, PD_SELF, PD_ON = range(3)

    class Error(Exception):
        pass

    def __init__(self, coin=None):
        self.logger = class_logger(__name__, self.__class__.__name__)
        self.allow_root = self.boolean('ALLOW_ROOT', False)
        self.host = self.default('HOST', 'localhost')
        self.rpc_host = self.default('RPC_HOST', 'localhost')
        self.elastic_host = self.default('ELASTIC_HOST', 'localhost')
        self.elastic_port = self.integer('ELASTIC_PORT', 9200)
        self.loop_policy = self.set_event_loop_policy()
        self.obsolete(['UTXO_MB', 'HIST_MB', 'NETWORK'])
        self.db_dir = self.required('DB_DIRECTORY')
        self.db_engine = self.default('DB_ENGINE', 'leveldb')
        self.trending_algorithms = [
            trending for trending in set(self.default('TRENDING_ALGORITHMS', 'zscore').split(' ')) if trending
        ]
        self.max_query_workers = self.integer('MAX_QUERY_WORKERS', None)
        self.individual_tag_indexes = self.boolean('INDIVIDUAL_TAG_INDEXES', True)
        self.track_metrics = self.boolean('TRACK_METRICS', False)
        self.websocket_host = self.default('WEBSOCKET_HOST', self.host)
        self.websocket_port = self.integer('WEBSOCKET_PORT', None)
        self.daemon_url = self.required('DAEMON_URL')
        if coin is not None:
            assert issubclass(coin, Coin)
            self.coin = coin
        else:
            coin_name = self.required('COIN').strip()
            network = self.default('NET', 'mainnet').strip()
            self.coin = Coin.lookup_coin_class(coin_name, network)
        self.es_index_prefix = self.default('ES_INDEX_PREFIX', '')
        self.es_mode = self.default('ES_MODE', 'writer')
        self.cache_MB = self.integer('CACHE_MB', 1200)
        self.reorg_limit = self.integer('REORG_LIMIT', self.coin.REORG_LIMIT)
        # Server stuff
        self.tcp_port = self.integer('TCP_PORT', None)
        self.udp_port = self.integer('UDP_PORT', self.tcp_port)
        self.ssl_port = self.integer('SSL_PORT', None)
        if self.ssl_port:
            self.ssl_certfile = self.required('SSL_CERTFILE')
            self.ssl_keyfile = self.required('SSL_KEYFILE')
        self.rpc_port = self.integer('RPC_PORT', 8000)
        self.prometheus_port = self.integer('PROMETHEUS_PORT', 0)
        self.max_subscriptions = self.integer('MAX_SUBSCRIPTIONS', 10000)
        self.banner_file = self.default('BANNER_FILE', None)
        self.tor_banner_file = self.default('TOR_BANNER_FILE', self.banner_file)
        self.anon_logs = self.boolean('ANON_LOGS', False)
        self.log_sessions = self.integer('LOG_SESSIONS', 3600)
        self.allow_lan_udp = self.boolean('ALLOW_LAN_UDP', False)
        # Peer discovery
        self.peer_discovery = self.peer_discovery_enum()
        self.peer_announce = self.boolean('PEER_ANNOUNCE', True)
        self.peer_hubs = self.extract_peer_hubs()
        self.force_proxy = self.boolean('FORCE_PROXY', False)
        self.tor_proxy_host = self.default('TOR_PROXY_HOST', 'localhost')
        self.tor_proxy_port = self.integer('TOR_PROXY_PORT', None)
        # The electrum client takes the empty string as unspecified
        self.payment_address = self.default('PAYMENT_ADDRESS', '')
        self.donation_address = self.default('DONATION_ADDRESS', '')
        # Server limits to help prevent DoS
        self.max_send = self.integer('MAX_SEND', 1000000)
        self.max_receive = self.integer('MAX_RECEIVE', 1000000)
        self.max_subs = self.integer('MAX_SUBS', 250000)
        self.max_sessions = self.sane_max_sessions()
        self.max_session_subs = self.integer('MAX_SESSION_SUBS', 50000)
        self.session_timeout = self.integer('SESSION_TIMEOUT', 600)
        self.drop_client = self.custom("DROP_CLIENT", None, re.compile)
        self.description = self.default('DESCRIPTION', '')
        self.daily_fee = self.string_amount('DAILY_FEE', '0')

        # Identities
        clearnet_identity = self.clearnet_identity()
        tor_identity = self.tor_identity(clearnet_identity)
        self.identities = [identity
                           for identity in (clearnet_identity, tor_identity)
                           if identity is not None]
        self.database_query_timeout = float(self.integer('QUERY_TIMEOUT_MS', 3000)) / 1000.0

    @classmethod
    def default(cls, envvar, default):
        return environ.get(envvar, default)

    @classmethod
    def boolean(cls, envvar, default):
        default = 'Yes' if default else ''
        return bool(cls.default(envvar, default).strip())

    @classmethod
    def required(cls, envvar):
        value = environ.get(envvar)
        if value is None:
            raise cls.Error(f'required envvar {envvar} not set')
        return value

    @classmethod
    def string_amount(cls, envvar, default):
        value = environ.get(envvar, default)
        amount_pattern = re.compile("[0-9]{0,10}(\.[0-9]{1,8})?")
        if len(value) > 0 and not amount_pattern.fullmatch(value):
            raise cls.Error(f'{value} is not a valid amount for {envvar}')
        return value

    @classmethod
    def integer(cls, envvar, default):
        value = environ.get(envvar)
        if value is None:
            return default
        try:
            return int(value)
        except Exception:
            raise cls.Error(f'cannot convert envvar {envvar} value {value} to an integer')

    @classmethod
    def custom(cls, envvar, default, parse):
        value = environ.get(envvar)
        if value is None:
            return default
        try:
            return parse(value)
        except Exception as e:
            raise cls.Error(f'cannot parse envvar {envvar} value {value}') from e

    @classmethod
    def obsolete(cls, envvars):
        bad = [envvar for envvar in envvars if environ.get(envvar)]
        if bad:
            raise cls.Error(f'remove obsolete environment variables {bad}')

    def set_event_loop_policy(self):
        policy_name = self.default('EVENT_LOOP_POLICY', None)
        if not policy_name:
            import asyncio
            return asyncio.get_event_loop_policy()
        elif policy_name == 'uvloop':
            import uvloop
            import asyncio
            loop_policy = uvloop.EventLoopPolicy()
            asyncio.set_event_loop_policy(loop_policy)
            return loop_policy
        raise self.Error(f'unknown event loop policy "{policy_name}"')

    def cs_host(self, *, for_rpc):
        """Returns the 'host' argument to pass to asyncio's create_server
        call.  The result can be a single host name string, a list of
        host name strings, or an empty string to bind to all interfaces.

        If rpc is True the host to use for the RPC server is returned.
        Otherwise the host to use for SSL/TCP servers is returned.
        """
        host = self.rpc_host if for_rpc else self.host
        result = [part.strip() for part in host.split(',')]
        if len(result) == 1:
            result = result[0]
        # An empty result indicates all interfaces, which we do not
        # permitted for an RPC server.
        if for_rpc and not result:
            result = 'localhost'
        if result == 'localhost':
            # 'localhost' resolves to ::1 (ipv6) on many systems, which fails on default setup of
            # docker, using 127.0.0.1 instead forces ipv4
            result = '127.0.0.1'
        return result

    def sane_max_sessions(self):
        """Return the maximum number of sessions to permit.  Normally this
        is MAX_SESSIONS.  However, to prevent open file exhaustion, ajdust
        downwards if running with a small open file rlimit."""
        env_value = self.integer('MAX_SESSIONS', 1000)
        nofile_limit = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
        # We give the DB 250 files; allow ElectrumX 100 for itself
        value = max(0, min(env_value, nofile_limit - 350))
        if value < env_value:
            self.logger.warning(f'lowered maximum sessions from {env_value:,d} to {value:,d} '
                                f'because your open file limit is {nofile_limit:,d}')
        return value

    def clearnet_identity(self):
        host = self.default('REPORT_HOST', None)
        if host is None:
            return None
        try:
            ip = ip_address(host)
        except ValueError:
            bad = (not lib_util.is_valid_hostname(host)
                   or host.lower() == 'localhost')
        else:
            bad = (ip.is_multicast or ip.is_unspecified
                   or (ip.is_private and self.peer_announce))
        if bad:
            raise self.Error(f'"{host}" is not a valid REPORT_HOST')
        tcp_port = self.integer('REPORT_TCP_PORT', self.tcp_port) or None
        ssl_port = self.integer('REPORT_SSL_PORT', self.ssl_port) or None
        if tcp_port == ssl_port:
            raise self.Error('REPORT_TCP_PORT and REPORT_SSL_PORT '
                             f'both resolve to {tcp_port}')
        return NetIdentity(
            host,
            tcp_port,
            ssl_port,
            ''
        )

    def tor_identity(self, clearnet):
        host = self.default('REPORT_HOST_TOR', None)
        if host is None:
            return None
        if not host.endswith('.onion'):
            raise self.Error(f'tor host "{host}" must end with ".onion"')

        def port(port_kind):
            """Returns the clearnet identity port, if any and not zero,
            otherwise the listening port."""
            result = 0
            if clearnet:
                result = getattr(clearnet, port_kind)
            return result or getattr(self, port_kind)

        tcp_port = self.integer('REPORT_TCP_PORT_TOR',
                                port('tcp_port')) or None
        ssl_port = self.integer('REPORT_SSL_PORT_TOR',
                                port('ssl_port')) or None
        if tcp_port == ssl_port:
            raise self.Error('REPORT_TCP_PORT_TOR and REPORT_SSL_PORT_TOR '
                             f'both resolve to {tcp_port}')

        return NetIdentity(
            host,
            tcp_port,
            ssl_port,
            '_tor',
        )

    def hosts_dict(self):
        return {identity.host: {'tcp_port': identity.tcp_port,
                                'ssl_port': identity.ssl_port}
                for identity in self.identities}

    def peer_discovery_enum(self):
        pd = self.default('PEER_DISCOVERY', 'on').strip().lower()
        if pd in ('off', ''):
            return self.PD_OFF
        elif pd == 'self':
            return self.PD_SELF
        else:
            return self.PD_ON

    def extract_peer_hubs(self):
        return [hub.strip() for hub in self.default('PEER_HUBS', '').split(',')]
