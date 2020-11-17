import os
import sys
import typing
import logging
from argparse import ArgumentParser
from contextlib import contextmanager
from typing import Tuple

import yaml
from lbry.utils.dirs import user_data_dir, user_download_dir
from lbry.error import InvalidCurrencyError
from lbry.dht import constants
from lbry.wallet.coinselection import COIN_SELECTION_STRATEGIES

log = logging.getLogger(__name__)


NOT_SET = type('NOT_SET', (object,), {})  # pylint: disable=invalid-name
T = typing.TypeVar('T')

CURRENCIES = {
    'BTC': {'type': 'crypto'},
    'LBC': {'type': 'crypto'},
    'USD': {'type': 'fiat'},
}


class Setting(typing.Generic[T]):

    def __init__(self, doc: str, default: typing.Optional[T] = None,
                 previous_names: typing.Optional[typing.List[str]] = None,
                 metavar: typing.Optional[str] = None):
        self.doc = doc
        self.default = default
        self.previous_names = previous_names or []
        self.metavar = metavar

    def __set_name__(self, owner, name):
        self.name = name  # pylint: disable=attribute-defined-outside-init

    @property
    def cli_name(self):
        return f"--{self.name.replace('_', '-')}"

    @property
    def no_cli_name(self):
        return f"--no-{self.name.replace('_', '-')}"

    def __get__(self, obj: typing.Optional['BaseConfig'], owner) -> T:
        if obj is None:
            return self
        for location in obj.search_order:
            if self.name in location:
                return location[self.name]
        return self.default

    def __set__(self, obj: 'BaseConfig', val: typing.Union[T, NOT_SET]):
        if val == NOT_SET:
            for location in obj.modify_order:
                if self.name in location:
                    del location[self.name]
        else:
            self.validate(val)
            for location in obj.modify_order:
                location[self.name] = val

    def validate(self, value):
        raise NotImplementedError()

    def deserialize(self, value):  # pylint: disable=no-self-use
        return value

    def serialize(self, value):  # pylint: disable=no-self-use
        return value

    def contribute_to_argparse(self, parser: ArgumentParser):
        parser.add_argument(
            self.cli_name,
            help=self.doc,
            metavar=self.metavar,
            default=NOT_SET
        )


class String(Setting[str]):
    def validate(self, value):
        assert isinstance(value, str), \
            f"Setting '{self.name}' must be a string."

    # TODO: removes this after pylint starts to understand generics
    def __get__(self, obj: typing.Optional['BaseConfig'], owner) -> str:  # pylint: disable=useless-super-delegation
        return super().__get__(obj, owner)


class Integer(Setting[int]):
    def validate(self, value):
        assert isinstance(value, int), \
            f"Setting '{self.name}' must be an integer."

    def deserialize(self, value):
        return int(value)


class Float(Setting[float]):
    def validate(self, value):
        assert isinstance(value, float), \
            f"Setting '{self.name}' must be a decimal."

    def deserialize(self, value):
        return float(value)


class Toggle(Setting[bool]):
    def validate(self, value):
        assert isinstance(value, bool), \
            f"Setting '{self.name}' must be a true/false value."

    def contribute_to_argparse(self, parser: ArgumentParser):
        parser.add_argument(
            self.cli_name,
            help=self.doc,
            action="store_true",
            default=NOT_SET
        )
        parser.add_argument(
            self.no_cli_name,
            help=f"Opposite of {self.cli_name}",
            dest=self.name,
            action="store_false",
            default=NOT_SET
        )


class Path(String):
    def __init__(self, doc: str, *args, default: str = '', **kwargs):
        super().__init__(doc, default, *args, **kwargs)

    def __get__(self, obj, owner) -> str:
        value = super().__get__(obj, owner)
        if isinstance(value, str):
            return os.path.expanduser(os.path.expandvars(value))
        return value


class MaxKeyFee(Setting[dict]):

    def validate(self, value):
        if value is not None:
            assert isinstance(value, dict) and set(value) == {'currency', 'amount'}, \
                f"Setting '{self.name}' must be a dict like \"{{'amount': 50.0, 'currency': 'USD'}}\"."
            if value["currency"] not in CURRENCIES:
                raise InvalidCurrencyError(value["currency"])

    @staticmethod
    def _parse_list(l):
        if l == ['null']:
            return None
        assert len(l) == 2, (
            'Max key fee is made up of either two values: '
            '"AMOUNT CURRENCY", or "null" (to set no limit)'
        )
        try:
            amount = float(l[0])
        except ValueError:
            raise AssertionError('First value in max key fee is a decimal: "AMOUNT CURRENCY"')
        currency = str(l[1]).upper()
        if currency not in CURRENCIES:
            raise InvalidCurrencyError(currency)
        return {'amount': amount, 'currency': currency}

    def deserialize(self, value):
        if value is None:
            return
        if isinstance(value, dict):
            return {
                'currency': value['currency'],
                'amount': float(value['amount']),
            }
        if isinstance(value, str):
            value = value.split()
        if isinstance(value, list):
            return self._parse_list(value)
        raise AssertionError('Invalid max key fee.')

    def contribute_to_argparse(self, parser: ArgumentParser):
        parser.add_argument(
            self.cli_name,
            help=self.doc,
            nargs='+',
            metavar=('AMOUNT', 'CURRENCY'),
            default=NOT_SET
        )
        parser.add_argument(
            self.no_cli_name,
            help="Disable maximum key fee check.",
            dest=self.name,
            const=None,
            action="store_const",
            default=NOT_SET
        )


class StringChoice(String):
    def __init__(self, doc: str, valid_values: typing.List[str], default: str, *args, **kwargs):
        super().__init__(doc, default, *args, **kwargs)
        if not valid_values:
            raise ValueError("No valid values provided")
        if default not in valid_values:
            raise ValueError(f"Default value must be one of: {', '.join(valid_values)}")
        self.valid_values = valid_values

    def validate(self, value):
        super().validate(value)
        if value not in self.valid_values:
            raise ValueError(f"Setting '{self.name}' value must be one of: {', '.join(self.valid_values)}")


class ListSetting(Setting[list]):

    def validate(self, value):
        assert isinstance(value, (tuple, list)), \
            f"Setting '{self.name}' must be a tuple or list."

    def contribute_to_argparse(self, parser: ArgumentParser):
        parser.add_argument(
            self.cli_name,
            help=self.doc,
            action='append'
        )


class Servers(ListSetting):

    def validate(self, value):
        assert isinstance(value, (tuple, list)), \
            f"Setting '{self.name}' must be a tuple or list of servers."
        for idx, server in enumerate(value):
            assert isinstance(server, (tuple, list)) and len(server) == 2, \
                f"Server defined '{server}' at index {idx} in setting " \
                f"'{self.name}' must be a tuple or list of two items."
            assert isinstance(server[0], str), \
                f"Server defined '{server}' at index {idx} in setting " \
                f"'{self.name}' must be have hostname as string in first position."
            assert isinstance(server[1], int), \
                f"Server defined '{server}' at index {idx} in setting " \
                f"'{self.name}' must be have port as int in second position."

    def deserialize(self, value):
        servers = []
        if isinstance(value, list):
            for server in value:
                if isinstance(server, str) and server.count(':') == 1:
                    host, port = server.split(':')
                    try:
                        servers.append((host, int(port)))
                    except ValueError:
                        pass
        return servers

    def serialize(self, value):
        if value:
            return [f"{host}:{port}" for host, port in value]
        return value


class Strings(ListSetting):

    def validate(self, value):
        assert isinstance(value, (tuple, list)), \
            f"Setting '{self.name}' must be a tuple or list of strings."
        for idx, string in enumerate(value):
            assert isinstance(string, str), \
                f"Value of '{string}' at index {idx} in setting " \
                f"'{self.name}' must be a string."


class EnvironmentAccess:
    PREFIX = 'LBRY_'

    def __init__(self, environ: dict):
        self.environ = environ

    def __contains__(self, item: str):
        return f'{self.PREFIX}{item.upper()}' in self.environ

    def __getitem__(self, item: str):
        return self.environ[f'{self.PREFIX}{item.upper()}']


class ArgumentAccess:

    def __init__(self, config: 'BaseConfig', args: dict):
        self.configuration = config
        self.args = {}
        if args:
            self.load(args)

    def load(self, args):
        for setting in self.configuration.get_settings():
            value = getattr(args, setting.name, NOT_SET)
            if value != NOT_SET and not (isinstance(setting, ListSetting) and value is None):
                self.args[setting.name] = setting.deserialize(value)

    def __contains__(self, item: str):
        return item in self.args

    def __getitem__(self, item: str):
        return self.args[item]


class ConfigFileAccess:

    def __init__(self, config: 'BaseConfig', path: str):
        self.configuration = config
        self.path = path
        self.data = {}
        if self.exists:
            self.load()

    @property
    def exists(self):
        return self.path and os.path.exists(self.path)

    def load(self):
        cls = type(self.configuration)
        with open(self.path, 'r') as config_file:
            raw = config_file.read()
        serialized = yaml.full_load(raw) or {}
        for key, value in serialized.items():
            attr = getattr(cls, key, None)
            if attr is None:
                for setting in self.configuration.settings:
                    if key in setting.previous_names:
                        attr = setting
                        break
            if attr is not None:
                self.data[key] = attr.deserialize(value)

    def save(self):
        cls = type(self.configuration)
        serialized = {}
        for key, value in self.data.items():
            attr = getattr(cls, key)
            serialized[key] = attr.serialize(value)
        with open(self.path, 'w') as config_file:
            config_file.write(yaml.safe_dump(serialized, default_flow_style=False))

    def upgrade(self) -> bool:
        upgraded = False
        for key in list(self.data):
            for setting in self.configuration.settings:
                if key in setting.previous_names:
                    self.data[setting.name] = self.data[key]
                    del self.data[key]
                    upgraded = True
                    break
        return upgraded

    def __contains__(self, item: str):
        return item in self.data

    def __getitem__(self, item: str):
        return self.data[item]

    def __setitem__(self, key, value):
        self.data[key] = value

    def __delitem__(self, key):
        del self.data[key]


TBC = typing.TypeVar('TBC', bound='BaseConfig')


class BaseConfig:

    config = Path("Path to configuration file.", metavar='FILE')

    def __init__(self, **kwargs):
        self.runtime = {}      # set internally or by various API calls
        self.arguments = {}    # from command line arguments
        self.environment = {}  # from environment variables
        self.persisted = {}    # from config file
        self._updating_config = False
        self.set(**kwargs)

    def set(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        return self

    @contextmanager
    def update_config(self):
        self._updating_config = True
        yield self
        self._updating_config = False
        if isinstance(self.persisted, ConfigFileAccess):
            self.persisted.save()

    @property
    def modify_order(self):
        locations = [self.runtime]
        if self._updating_config:
            locations.append(self.persisted)
        return locations

    @property
    def search_order(self):
        return [
            self.runtime,
            self.arguments,
            self.environment,
            self.persisted
        ]

    @classmethod
    def get_settings(cls):
        for attr in dir(cls):
            setting = getattr(cls, attr)
            if isinstance(setting, Setting):
                yield setting

    @property
    def settings(self):
        return self.get_settings()

    @property
    def settings_dict(self):
        return {
            setting.name: getattr(self, setting.name) for setting in self.settings
        }

    @classmethod
    def create_from_arguments(cls, args) -> TBC:
        conf = cls()
        conf.set_arguments(args)
        conf.set_environment()
        conf.set_persisted()
        return conf

    @classmethod
    def contribute_to_argparse(cls, parser: ArgumentParser):
        for setting in cls.get_settings():
            setting.contribute_to_argparse(parser)

    def set_arguments(self, args):
        self.arguments = ArgumentAccess(self, args)

    def set_environment(self, environ=None):
        self.environment = EnvironmentAccess(environ or os.environ)

    def set_persisted(self, config_file_path=None):
        if config_file_path is None:
            config_file_path = self.config

        if not config_file_path:
            return

        ext = os.path.splitext(config_file_path)[1]
        assert ext in ('.yml', '.yaml'),\
            f"File extension '{ext}' is not supported, " \
            f"configuration file must be in YAML (.yaml)."

        self.persisted = ConfigFileAccess(self, config_file_path)
        if self.persisted.upgrade():
            self.persisted.save()


class TranscodeConfig(BaseConfig):

    ffmpeg_path = String('A list of places to check for ffmpeg and ffprobe. '
                         f'$data_dir/ffmpeg/bin and $PATH are checked afterward. Separator: {os.pathsep}',
                         '', previous_names=['ffmpeg_folder'])
    video_encoder = String('FFmpeg codec and parameters for the video encoding. '
                           'Example: libaom-av1 -crf 25 -b:v 0 -strict experimental',
                           'libx264 -crf 21 -preset faster -pix_fmt yuv420p')
    video_bitrate_maximum = Integer('Maximum bits per second allowed for video streams (0 to disable).', 8400000)
    video_scaler = String('FFmpeg scaling parameters for reducing bitrate. '
                          'Example: -vf "scale=-2:720,fps=24" -maxrate 5M -bufsize 3M',
                          r'-vf "scale=if(gte(iw\,ih)\,min(1920\,iw)\,-2):if(lt(iw\,ih)\,min(1920\,ih)\,-2)" '
                          r'-maxrate 8400K -bufsize 5000K')
    audio_encoder = String('FFmpeg codec and parameters for the audio encoding. '
                           'Example: libopus -b:a 128k',
                           'aac -b:a 160k')
    volume_filter = String('FFmpeg filter for audio normalization.', '-af loudnorm')
    volume_analysis_time = Integer('Maximum seconds into the file that we examine audio volume (0 to disable).', 240)


class CLIConfig(TranscodeConfig):

    api = String('Host name and port for lbrynet daemon API.', 'localhost:5279', metavar='HOST:PORT')

    @property
    def api_connection_url(self) -> str:
        return f"http://{self.api}/lbryapi"

    @property
    def api_host(self):
        return self.api.split(':')[0]

    @property
    def api_port(self):
        return int(self.api.split(':')[1])


class Config(CLIConfig):
    db_url = String("Database connection URL, uses a local file based SQLite by default.")
    workers = Integer(
        "Multiprocessing, specify number of worker processes lbrynet can start (including main process)."
        " (-1: threads only, 0: equal to number of CPUs, >1: specific number of processes)", -1
    )
    console = StringChoice(
        "Basic text console output or advanced colored output with progress bars.",
        ["basic", "advanced", "none"], "advanced"
    )

    # directories
    download_dir = Path("Directory to store downloaded files.", metavar='DIR')
    data_dir = Path("Main directory containing blobs, wallets and blockchain data.", metavar='DIR')
    blob_dir = Path("Directory to store blobs (default: 'data_dir'/blobs).", metavar='DIR')
    wallet_dir = Path("Directory to store wallets (default: 'data_dir'/wallets).", metavar='DIR')
    wallets = Strings(
        "Wallet files in 'wallet_dir' to load at startup.", ['default_wallet']
    )
    create_default_wallet = Toggle(
        "Create an initial wallet if it does not exist on startup.", True
    )
    create_default_account = Toggle(
        "Create an initial account if it does not exist in the default wallet.", True
    )

    # network
    use_upnp = Toggle(
        "Use UPnP to setup temporary port redirects for the DHT and the hosting of blobs. If you manually forward"
        "ports or have firewall rules you likely want to disable this.", True
    )
    udp_port = Integer("UDP port for communicating on the LBRY DHT", 4444, previous_names=['dht_node_port'])
    tcp_port = Integer("TCP port to listen for incoming blob requests", 3333, previous_names=['peer_port'])
    prometheus_port = Integer("Port to expose prometheus metrics (off by default)", 0)
    network_interface = String("Interface to use for the DHT and blob exchange", '0.0.0.0')

    # routing table
    split_buckets_under_index = Integer(
        "Routing table bucket index below which we always split the bucket if given a new key to add to it and "
        "the bucket is full. As this value is raised the depth of the routing table (and number of peers in it) "
        "will increase. This setting is used by seed nodes, you probably don't want to change it during normal "
        "use.", 1
    )

    # protocol timeouts
    download_timeout = Float("Cumulative timeout for a stream to begin downloading before giving up", 30.0)
    blob_download_timeout = Float("Timeout to download a blob from a peer", 30.0)
    peer_connect_timeout = Float("Timeout to establish a TCP connection to a peer", 3.0)
    node_rpc_timeout = Float("Timeout when making a DHT request", constants.RPC_TIMEOUT)

    # blob announcement and download
    save_blobs = Toggle("Save encrypted blob files for hosting, otherwise download blobs to memory only.", True)
    blob_lru_cache_size = Integer(
        "LRU cache size for decrypted downloaded blobs used to minimize re-downloading the same blobs when "
        "replying to a range request. Set to 0 to disable.", 32
    )
    announce_head_and_sd_only = Toggle(
        "Announce only the descriptor and first (rather than all) data blob for a stream to the DHT", True,
        previous_names=['announce_head_blobs_only']
    )
    concurrent_blob_announcers = Integer(
        "Number of blobs to iteratively announce at once, set to 0 to disable", 10,
        previous_names=['concurrent_announcers']
    )
    max_connections_per_download = Integer(
        "Maximum number of peers to connect to while downloading a blob", 4,
        previous_names=['max_connections_per_stream']
    )
    fixed_peer_delay = Float(
        "Amount of seconds before adding the reflector servers as potential peers to download from in case dht"
        "peers are not found or are slow", 2.0
    )
    max_key_fee = MaxKeyFee(
        "Don't download streams with fees exceeding this amount. When set to "
        "null, the amount is unbounded.", {'currency': 'USD', 'amount': 50.0}
    )
    max_wallet_server_fee = String("Maximum daily LBC amount allowed as payment for wallet servers.", "0.0")

    # reflector settings
    reflect_streams = Toggle(
        "Upload completed streams (published and downloaded) reflector in order to re-host them", True,
        previous_names=['reflect_uploads']
    )
    concurrent_reflector_uploads = Integer(
        "Maximum number of streams to upload to a reflector server at a time", 10
    )

    # servers
    reflector_servers = Servers("Reflector re-hosting servers", [
        ('reflector.lbry.com', 5566)
    ])
    known_full_nodes = Servers("Full blockchain nodes", [
        ('spv11.lbry.com', 50001),
        ('spv12.lbry.com', 50001),
        ('spv13.lbry.com', 50001),
        ('spv14.lbry.com', 50001),
        ('spv15.lbry.com', 50001),
        ('spv16.lbry.com', 50001),
        ('spv17.lbry.com', 50001),
        ('spv18.lbry.com', 50001),
        ('spv19.lbry.com', 50001),
    ])
    known_dht_nodes = Servers("Known nodes for bootstrapping connection to the DHT", [
        ('lbrynet1.lbry.com', 4444),  # US EAST
        ('lbrynet2.lbry.com', 4444),  # US WEST
        ('lbrynet3.lbry.com', 4444),  # EU
        ('lbrynet4.lbry.com', 4444)  # ASIA
    ])

    comment_server = String("Comment server API URL", "https://comments.lbry.com/api")

    # blockchain
    blockchain = StringChoice("Blockchain network type.", ["mainnet", "regtest", "testnet"], "mainnet")
    lbrycrd_rpc_user = String("Username for connecting to lbrycrd.", "rpcuser")
    lbrycrd_rpc_pass = String("Password for connecting to lbrycrd.", "rpcpassword")
    lbrycrd_rpc_host = String("Hostname for connecting to lbrycrd.", "localhost")
    lbrycrd_rpc_port = Integer("Port for connecting to lbrycrd.", 9245)
    lbrycrd_peer_port = Integer("Peer port for lbrycrd.", 9246)
    lbrycrd_zmq = String("ZMQ events address.")
    lbrycrd_dir = Path("Directory containing lbrycrd data.", metavar='DIR')
    spv_address_filters = Toggle(
        "Generate Golomb-Rice coding filters for blocks and transactions. Enables "
        "light client to synchronize with a full node.",
        True
    )

    # daemon
    save_files = Toggle("Save downloaded files when calling `get` by default", True)
    components_to_skip = Strings("components which will be skipped during start-up of daemon", [])
    share_usage_data = Toggle(
        "Whether to share usage stats and diagnostic info with LBRY.", False,
        previous_names=['upload_log', 'upload_log', 'share_debug_info']
    )
    track_bandwidth = Toggle("Track bandwidth usage", True)

    # media server
    streaming_server = String('Host name and port to serve streaming media over range requests',
                              'localhost:5280', metavar='HOST:PORT')
    streaming_get = Toggle("Enable the /get endpoint for the streaming media server. "
                           "Disable to prevent new streams from being added.", True)

    coin_selection_strategy = StringChoice(
        "Strategy to use when selecting UTXOs for a transaction",
        COIN_SELECTION_STRATEGIES, "standard")

    save_resolved_claims = Toggle(
        "Save content claims to the database when they are resolved to keep file_list up to date, "
        "only disable this if file_x commands are not needed", True
    )

    @property
    def streaming_host(self):
        return self.streaming_server.split(':')[0]

    @property
    def streaming_port(self):
        return int(self.streaming_server.split(':')[1])

    @classmethod
    def with_null_dir(cls):
        return cls.with_same_dir('/dev/null')

    @classmethod
    def with_same_dir(cls, same_dir):
        return cls(
            data_dir=same_dir,
            download_dir=same_dir,
            wallet_dir=same_dir,
            lbrycrd_dir=same_dir,
        )

    def set_default_paths(self):
        if 'darwin' in sys.platform.lower():
            get_directories = get_darwin_directories
        elif 'win' in sys.platform.lower():
            get_directories = get_windows_directories
        elif 'linux' in sys.platform.lower():
            get_directories = get_linux_directories
        else:
            return
        cls = type(self)
        cls.data_dir.default, cls.wallet_dir.default,\
            cls.blob_dir.default, cls.download_dir.default = get_directories()
        old_settings_file = os.path.join(self.data_dir, 'daemon_settings.yml')
        if os.path.exists(old_settings_file):
            cls.config.default = old_settings_file
        else:
            cls.config.default = os.path.join(self.data_dir, 'settings.yml')
        if self.data_dir != cls.data_dir.default:
            cls.blob_dir.default = os.path.join(self.data_dir, 'blobs')
            cls.wallet_dir.default = os.path.join(self.data_dir, 'wallets')

    @property
    def log_file_path(self):
        return os.path.join(self.data_dir, 'daemon.log')

    @property
    def db_url_or_default(self):
        if self.db_url:
            return self.db_url
        return 'sqlite:///'+os.path.join(self.data_dir, f'{self.blockchain}.db')


def get_windows_directories() -> Tuple[str, str, str, str]:
    # very old
    data_dir = user_data_dir('lbrynet', roaming=True)
    blob_dir = os.path.join(data_dir, 'blobfiles')
    wallet_dir = os.path.join(user_data_dir('lbryum', roaming=True), 'wallets')
    if os.path.isdir(blob_dir) or os.path.isdir(wallet_dir):
        return data_dir, wallet_dir, blob_dir, user_download_dir()
    # old
    data_dir = user_data_dir('lbrynet', 'lbry')
    blob_dir = os.path.join(data_dir, 'blobfiles')
    wallet_dir = os.path.join(user_data_dir('lbryum', 'lbry'), 'wallets')
    if os.path.isdir(blob_dir) and os.path.isdir(wallet_dir):
        return data_dir, wallet_dir, blob_dir, user_download_dir()
    # new
    return get_universal_directories()


def get_darwin_directories() -> Tuple[str, str, str, str]:
    data_dir = user_data_dir('LBRY')
    blob_dir = os.path.join(data_dir, 'blobfiles')
    wallet_dir = os.path.expanduser('~/.lbryum/wallets')
    if os.path.isdir(blob_dir) or os.path.isdir(wallet_dir):
        return data_dir, wallet_dir, blob_dir, user_download_dir()
    return get_universal_directories()


def get_linux_directories() -> Tuple[str, str, str, str]:
    # very old
    data_dir = os.path.expanduser('~/.lbrynet')
    blob_dir = os.path.join(data_dir, 'blobfiles')
    wallet_dir = os.path.join(os.path.expanduser('~/.lbryum'), 'wallets')
    if os.path.isdir(blob_dir) or os.path.isdir(wallet_dir):
        return data_dir, wallet_dir, blob_dir, user_download_dir()
    # old
    data_dir = user_data_dir('lbry/lbrynet')
    blob_dir = os.path.join(data_dir, 'blobfiles')
    wallet_dir = user_data_dir('lbry/lbryum/wallets')
    if os.path.isdir(blob_dir) or os.path.isdir(wallet_dir):
        return data_dir, wallet_dir, blob_dir, user_download_dir()
    # new
    return get_universal_directories()


def get_universal_directories() -> Tuple[str, str, str, str]:
    lbrynet_dir = user_data_dir('lbrynet', 'LBRY')
    return (
        lbrynet_dir,
        os.path.join(lbrynet_dir, 'wallets'),
        os.path.join(lbrynet_dir, 'blobs'),
        user_download_dir()
    )
