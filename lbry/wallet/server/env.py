# Copyright (c) 2016, Neil Booth
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.

import math
import re
import resource
from os import environ
from collections import namedtuple
from ipaddress import ip_address

from lbry.wallet.server.util import class_logger
from lbry.wallet.server.coin import Coin, LBC, LBCTestNet, LBCRegTest
import lbry.wallet.server.util as lib_util


NetIdentity = namedtuple('NetIdentity', 'host tcp_port ssl_port nick_suffix')


class Env:

    # Peer discovery
    PD_OFF, PD_SELF, PD_ON = range(3)

    class Error(Exception):
        pass

    def __init__(self, coin=None, db_dir=None, daemon_url=None, host=None, rpc_host=None, elastic_host=None,
                 elastic_port=None, loop_policy=None, max_query_workers=None, websocket_host=None, websocket_port=None,
                 chain=None, es_index_prefix=None, es_mode=None, cache_MB=None, reorg_limit=None, tcp_port=None,
                 udp_port=None, ssl_port=None, ssl_certfile=None, ssl_keyfile=None, rpc_port=None,
                 prometheus_port=None, max_subscriptions=None, banner_file=None, anon_logs=None, log_sessions=None,
                 allow_lan_udp=None, cache_all_tx_hashes=None, cache_all_claim_txos=None, country=None,
                 payment_address=None, donation_address=None, max_send=None, max_receive=None, max_sessions=None,
                 session_timeout=None, drop_client=None, description=None, daily_fee=None,
                 database_query_timeout=None, db_max_open_files=512):
        self.logger = class_logger(__name__, self.__class__.__name__)

        self.db_dir = db_dir if db_dir is not None else self.required('DB_DIRECTORY')
        self.daemon_url = daemon_url if daemon_url is not None else self.required('DAEMON_URL')
        self.db_max_open_files = db_max_open_files

        self.host = host if host is not None else self.default('HOST', 'localhost')
        self.rpc_host = rpc_host if rpc_host is not None else self.default('RPC_HOST', 'localhost')
        self.elastic_host = elastic_host if elastic_host is not None else self.default('ELASTIC_HOST', 'localhost')
        self.elastic_port = elastic_port if elastic_port is not None else self.integer('ELASTIC_PORT', 9200)
        self.loop_policy = self.set_event_loop_policy(
            loop_policy if loop_policy is not None else self.default('EVENT_LOOP_POLICY', None)
        )
        self.obsolete(['UTXO_MB', 'HIST_MB', 'NETWORK'])
        self.max_query_workers = max_query_workers if max_query_workers is not None else self.integer('MAX_QUERY_WORKERS', 4)
        self.websocket_host = websocket_host if websocket_host is not None else self.default('WEBSOCKET_HOST', self.host)
        self.websocket_port = websocket_port if websocket_port is not None else self.integer('WEBSOCKET_PORT', None)
        if coin is not None:
            assert issubclass(coin, Coin)
            self.coin = coin
        else:
            chain = chain if chain is not None else self.default('NET', 'mainnet').strip().lower()
            if chain == 'mainnet':
                self.coin = LBC
            elif chain == 'testnet':
                self.coin = LBCTestNet
            else:
                self.coin = LBCRegTest
        self.es_index_prefix = es_index_prefix if es_index_prefix is not None else self.default('ES_INDEX_PREFIX', '')
        self.es_mode = es_mode if es_mode is not None else self.default('ES_MODE', 'writer')
        self.cache_MB = cache_MB if cache_MB is not None else self.integer('CACHE_MB', 1024)
        self.reorg_limit = reorg_limit if reorg_limit is not None else self.integer('REORG_LIMIT', self.coin.REORG_LIMIT)
        # Server stuff
        self.tcp_port = tcp_port if tcp_port is not None else self.integer('TCP_PORT', None)
        self.udp_port = udp_port if udp_port is not None else self.integer('UDP_PORT', self.tcp_port)
        self.ssl_port = ssl_port if ssl_port is not None else self.integer('SSL_PORT', None)
        if self.ssl_port:
            self.ssl_certfile = ssl_certfile if ssl_certfile is not None else self.required('SSL_CERTFILE')
            self.ssl_keyfile = ssl_keyfile if ssl_keyfile is not None else self.required('SSL_KEYFILE')
        self.rpc_port = rpc_port if rpc_port is not None else self.integer('RPC_PORT', 8000)
        self.prometheus_port = prometheus_port if prometheus_port is not None else self.integer('PROMETHEUS_PORT', 0)
        self.max_subscriptions = max_subscriptions if max_subscriptions is not None else self.integer('MAX_SUBSCRIPTIONS', 10000)
        self.banner_file = banner_file if banner_file is not None else self.default('BANNER_FILE', None)
        # self.tor_banner_file = self.default('TOR_BANNER_FILE', self.banner_file)
        self.anon_logs = anon_logs if anon_logs is not None else self.boolean('ANON_LOGS', False)
        self.log_sessions = log_sessions if log_sessions is not None else self.integer('LOG_SESSIONS', 3600)
        self.allow_lan_udp = allow_lan_udp if allow_lan_udp is not None else self.boolean('ALLOW_LAN_UDP', False)
        self.cache_all_tx_hashes = cache_all_tx_hashes if cache_all_tx_hashes is not None else self.boolean('CACHE_ALL_TX_HASHES', False)
        self.cache_all_claim_txos = cache_all_claim_txos if cache_all_claim_txos is not None else self.boolean('CACHE_ALL_CLAIM_TXOS', False)
        self.country = country if country is not None else self.default('COUNTRY', 'US')
        # Peer discovery
        self.peer_discovery = self.peer_discovery_enum()
        self.peer_announce = self.boolean('PEER_ANNOUNCE', True)
        self.peer_hubs = self.extract_peer_hubs()
        # self.tor_proxy_host = self.default('TOR_PROXY_HOST', 'localhost')
        # self.tor_proxy_port = self.integer('TOR_PROXY_PORT', None)
        # The electrum client takes the empty string as unspecified
        self.payment_address = payment_address if payment_address is not None else self.default('PAYMENT_ADDRESS', '')
        self.donation_address = donation_address if donation_address is not None else self.default('DONATION_ADDRESS', '')
        # Server limits to help prevent DoS
        self.max_send = max_send if max_send is not None else self.integer('MAX_SEND', 1000000)
        self.max_receive = max_receive if max_receive is not None else self.integer('MAX_RECEIVE', 1000000)
        # self.max_subs = self.integer('MAX_SUBS', 250000)
        self.max_sessions = max_sessions if max_sessions is not None else self.sane_max_sessions()
        # self.max_session_subs = self.integer('MAX_SESSION_SUBS', 50000)
        self.session_timeout = session_timeout if session_timeout is not None else self.integer('SESSION_TIMEOUT', 600)
        self.drop_client = drop_client if drop_client is not None else self.custom("DROP_CLIENT", None, re.compile)
        self.description = description if description is not None else self.default('DESCRIPTION', '')
        self.daily_fee = daily_fee if daily_fee is not None else self.string_amount('DAILY_FEE', '0')

        # Identities
        clearnet_identity = self.clearnet_identity()
        tor_identity = self.tor_identity(clearnet_identity)
        self.identities = [identity
                           for identity in (clearnet_identity, tor_identity)
                           if identity is not None]
        self.database_query_timeout = database_query_timeout if database_query_timeout is not None else \
            (float(self.integer('QUERY_TIMEOUT_MS', 10000)) / 1000.0)

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

    @classmethod
    def set_event_loop_policy(cls, policy_name: str = None):
        if not policy_name or policy_name == 'default':
            import asyncio
            return asyncio.get_event_loop_policy()
        elif policy_name == 'uvloop':
            import uvloop
            import asyncio
            loop_policy = uvloop.EventLoopPolicy()
            asyncio.set_event_loop_policy(loop_policy)
            return loop_policy
        raise cls.Error(f'unknown event loop policy "{policy_name}"')

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
        return [hub.strip() for hub in self.default('PEER_HUBS', '').split(',') if hub.strip()]

    @classmethod
    def contribute_to_arg_parser(cls, parser):
        parser.add_argument('--db_dir', type=str, help='path of the directory containing lbry-leveldb')
        parser.add_argument('--daemon_url',
                            help='URL for rpc from lbrycrd, <rpcuser>:<rpcpassword>@<lbrycrd rpc ip><lbrycrd rpc port>')
        parser.add_argument('--db_max_open_files', type=int, default=512,
                            help='number of files leveldb can have open at a time')
        parser.add_argument('--host', type=str, default=cls.default('HOST', 'localhost'),
                            help='Interface for hub server to listen on')
        parser.add_argument('--tcp_port', type=int, default=cls.integer('TCP_PORT', 50001),
                            help='TCP port to listen on for hub server')
        parser.add_argument('--udp_port', type=int, default=cls.integer('UDP_PORT', 50001),
                            help='UDP port to listen on for hub server')
        parser.add_argument('--rpc_host', default=cls.default('RPC_HOST', 'localhost'), type=str,
                            help='Listening interface for admin rpc')
        parser.add_argument('--rpc_port', default=cls.integer('RPC_PORT', 8000), type=int,
                            help='Listening port for admin rpc')
        parser.add_argument('--websocket_host', default=cls.default('WEBSOCKET_HOST', 'localhost'), type=str,
                            help='Listening interface for websocket')
        parser.add_argument('--websocket_port', default=cls.integer('WEBSOCKET_PORT', None), type=int,
                            help='Listening port for websocket')

        parser.add_argument('--ssl_port', default=cls.integer('SSL_PORT', None), type=int,
                            help='SSL port to listen on for hub server')
        parser.add_argument('--ssl_certfile', default=cls.default('SSL_CERTFILE', None), type=str,
                            help='Path to SSL cert file')
        parser.add_argument('--ssl_keyfile', default=cls.default('SSL_KEYFILE', None), type=str,
                            help='Path to SSL key file')
        parser.add_argument('--reorg_limit', default=cls.integer('REORG_LIMIT', 200), type=int, help='Max reorg depth')
        parser.add_argument('--elastic_host', default=cls.default('ELASTIC_HOST', 'localhost'), type=str,
                            help='elasticsearch host')
        parser.add_argument('--elastic_port', default=cls.integer('ELASTIC_PORT', 9200), type=int,
                            help='elasticsearch port')
        parser.add_argument('--es_mode', default=cls.default('ES_MODE', 'writer'), type=str,
                            choices=['reader', 'writer'])
        parser.add_argument('--es_index_prefix', default=cls.default('ES_INDEX_PREFIX', ''), type=str)
        parser.add_argument('--loop_policy', default=cls.default('EVENT_LOOP_POLICY', 'default'), type=str,
                            choices=['default', 'uvloop'])
        parser.add_argument('--max_query_workers', type=int, default=cls.integer('MAX_QUERY_WORKERS', 4),
                            help='number of threads used by the request handler to read the database')
        parser.add_argument('--cache_MB', type=int, default=cls.integer('CACHE_MB', 1024),
                            help='size of the leveldb lru cache, in megabytes')
        parser.add_argument('--cache_all_tx_hashes', type=bool,
                            help='Load all tx hashes into memory. This will make address subscriptions and sync, '
                                 'resolve, transaction fetching, and block sync all faster at the expense of higher '
                                 'memory usage')
        parser.add_argument('--cache_all_claim_txos', type=bool,
                            help='Load all claim txos into memory. This will make address subscriptions and sync, '
                                 'resolve, transaction fetching, and block sync all faster at the expense of higher '
                                 'memory usage')
        parser.add_argument('--prometheus_port', type=int, default=cls.integer('PROMETHEUS_PORT', 0),
                            help='port for hub prometheus metrics to listen on, disabled by default')
        parser.add_argument('--max_subscriptions', type=int, default=cls.integer('MAX_SUBSCRIPTIONS', 10000),
                            help='max subscriptions per connection')
        parser.add_argument('--banner_file', type=str, default=cls.default('BANNER_FILE', None),
                            help='path to file containing banner text')
        parser.add_argument('--anon_logs', type=bool, default=cls.boolean('ANON_LOGS', False),
                            help="don't log ip addresses")
        parser.add_argument('--allow_lan_udp', type=bool, default=cls.boolean('ALLOW_LAN_UDP', False),
                            help='reply to hub UDP ping messages from LAN ip addresses')
        parser.add_argument('--country', type=str, default=cls.default('COUNTRY', 'US'), help='')
        parser.add_argument('--max_send', type=int, default=cls.default('MAX_SEND', 1000000), help='')
        parser.add_argument('--max_receive', type=int, default=cls.default('MAX_RECEIVE', 1000000), help='')
        parser.add_argument('--max_sessions', type=int, default=cls.default('MAX_SESSIONS', 1000), help='')
        parser.add_argument('--session_timeout', type=int, default=cls.default('SESSION_TIMEOUT', 600), help='')
        parser.add_argument('--drop_client', type=str, default=cls.default('DROP_CLIENT', None), help='')
        parser.add_argument('--description', type=str, default=cls.default('DESCRIPTION', ''), help='')
        parser.add_argument('--daily_fee', type=float, default=cls.default('DAILY_FEE', 0.0), help='')
        parser.add_argument('--payment_address', type=str, default=cls.default('PAYMENT_ADDRESS', ''), help='')
        parser.add_argument('--donation_address', type=str, default=cls.default('DONATION_ADDRESS', ''), help='')
        parser.add_argument('--chain', type=str, default=cls.default('NET', 'mainnet'),
                            help="Which chain to use, default is mainnet")
        parser.add_argument('--query_timeout_ms', type=int, default=cls.integer('QUERY_TIMEOUT_MS', 10000),
                            help="elasticsearch query timeout")

    @classmethod
    def from_arg_parser(cls, args):
        return cls(
            db_dir=args.db_dir, daemon_url=args.daemon_url, db_max_open_files=args.db_max_open_files,
            host=args.host, rpc_host=args.rpc_host, elastic_host=args.elastic_host, elastic_port=args.elastic_port,
            loop_policy=args.loop_policy, max_query_workers=args.max_query_workers, websocket_host=args.websocket_host,
            websocket_port=args.websocket_port, chain=args.chain, es_index_prefix=args.es_index_prefix,
            es_mode=args.es_mode, cache_MB=args.cache_MB, reorg_limit=args.reorg_limit, tcp_port=args.tcp_port,
            udp_port=args.udp_port, ssl_port=args.ssl_port, ssl_certfile=args.ssl_certfile,
            ssl_keyfile=args.ssl_keyfile, rpc_port=args.rpc_port, prometheus_port=args.prometheus_port,
            max_subscriptions=args.max_subscriptions, banner_file=args.banner_file, anon_logs=args.anon_logs,
            log_sessions=None, allow_lan_udp=args.allow_lan_udp,
            cache_all_tx_hashes=args.cache_all_tx_hashes, cache_all_claim_txos=args.cache_all_claim_txos,
            country=args.country, payment_address=args.payment_address, donation_address=args.donation_address,
            max_send=args.max_send, max_receive=args.max_receive, max_sessions=args.max_sessions,
            session_timeout=args.session_timeout, drop_client=args.drop_client, description=args.description,
            daily_fee=args.daily_fee, database_query_timeout=(args.query_timeout_ms / 1000)
        )
