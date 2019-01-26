import os
import re
import sys
import typing
import logging
import yaml
from argparse import ArgumentParser
from contextlib import contextmanager
from appdirs import user_data_dir, user_config_dir
from lbrynet.error import InvalidCurrencyError
from lbrynet.dht import constants

log = logging.getLogger(__name__)


NOT_SET = type(str('NOT_SET'), (object,), {})
T = typing.TypeVar('T')

KB = 2 ** 10
MB = 2 ** 20

ANALYTICS_ENDPOINT = 'https://api.segment.io/v1'
ANALYTICS_TOKEN = 'Ax5LZzR1o3q3Z3WjATASDwR5rKyHH0qOIRIbLmMXn2H='
API_ADDRESS = 'lbryapi'
APP_NAME = 'LBRY'
BLOBFILES_DIR = 'blobfiles'
CRYPTSD_FILE_EXTENSION = '.cryptsd'
CURRENCIES = {
    'BTC': {'type': 'crypto'},
    'LBC': {'type': 'crypto'},
    'USD': {'type': 'fiat'},
}
ICON_PATH = 'icons' if 'win' in sys.platform else 'app.icns'
LOG_FILE_NAME = 'lbrynet.log'
LOG_POST_URL = 'https://lbry.io/log-upload'
MAX_BLOB_REQUEST_SIZE = 64 * KB
MAX_HANDSHAKE_SIZE = 64 * KB
MAX_REQUEST_SIZE = 64 * KB
MAX_RESPONSE_INFO_SIZE = 64 * KB
MAX_BLOB_INFOS_TO_REQUEST = 20
PROTOCOL_PREFIX = 'lbry'
SLACK_WEBHOOK = (
    'nUE0pUZ6Yl9bo29epl5moTSwnl5wo20ip2IlqzywMKZiIQSFZR5'
    'AHx4mY0VmF0WQZ1ESEP9kMHZlp1WzJwWOoKN3ImR1M2yUAaMyqGZ='
)
HEADERS_FILE_SHA256_CHECKSUM = (
    366295, 'b0c8197153a33ccbc52fb81a279588b6015b68b7726f73f6a2b81f7e25bfe4b9'
)


class Setting(typing.Generic[T]):

    def __init__(self, doc: str, default: typing.Optional[T] = None,
                 previous_names: typing.Optional[typing.List[str]] = None,
                 metavar: typing.Optional[str] = None):
        self.doc = doc
        self.default = default
        self.previous_names = previous_names or []
        self.metavar = metavar

    def __set_name__(self, owner, name):
        self.name = name

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

    def validate(self, val):
        raise NotImplementedError()

    def deserialize(self, value):
        return value

    def serialize(self, value):
        return value

    def contribute_to_argparse(self, parser: ArgumentParser):
        parser.add_argument(
            self.cli_name,
            help=self.doc,
            metavar=self.metavar,
            default=NOT_SET
        )


class String(Setting[str]):
    def validate(self, val):
        assert isinstance(val, str), \
            f"Setting '{self.name}' must be a string."


class Integer(Setting[int]):
    def validate(self, val):
        assert isinstance(val, int), \
            f"Setting '{self.name}' must be an integer."

    def deserialize(self, value):
        return int(value)


class Float(Setting[float]):
    def validate(self, val):
        assert isinstance(val, float), \
            f"Setting '{self.name}' must be a decimal."

    def deserialize(self, value):
        return float(value)


class Toggle(Setting[bool]):
    def validate(self, val):
        assert isinstance(val, bool), \
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
            help=f"Opposite of --{self.cli_name}",
            dest=self.name,
            action="store_false",
            default=NOT_SET
        )


class Path(String):
    def __init__(self, doc: str, default: str = '', *args, **kwargs):
        super().__init__(doc, default, *args, **kwargs)

    def __get__(self, obj, owner):
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
        assert len(l) == 2, 'Max key fee is made up of two values: "AMOUNT CURRENCY".'
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
            nargs=2,
            metavar=('AMOUNT', 'CURRENCY'),
            default=NOT_SET
        )
        parser.add_argument(
            self.no_cli_name,
            help=f"Disable maximum key fee check.",
            dest=self.name,
            const=None,
            action="store_const",
            default=NOT_SET
        )


class Servers(Setting[list]):

    def validate(self, val):
        assert isinstance(val, (tuple, list)), \
            f"Setting '{self.name}' must be a tuple or list of servers."
        for idx, server in enumerate(val):
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

    def contribute_to_argparse(self, parser: ArgumentParser):
        parser.add_argument(
            self.cli_name,
            nargs="*",
            help=self.doc,
            default=NOT_SET
        )


class Strings(Setting[list]):

    def validate(self, val):
        assert isinstance(val, (tuple, list)), \
            f"Setting '{self.name}' must be a tuple or list of strings."
        for idx, string in enumerate(val):
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
            if value != NOT_SET:
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
        serialized = yaml.load(raw) or {}
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


class BaseConfig:

    config = Path("Path to configuration file.", metavar='FILE')

    def __init__(self, **kwargs):
        self.runtime = {}      # set internally or by various API calls
        self.arguments = {}    # from command line arguments
        self.environment = {}  # from environment variables
        self.persisted = {}    # from config file
        self._updating_config = False
        for key, value in kwargs.items():
            setattr(self, key, value)

    @contextmanager
    def update_config(self):
        if not isinstance(self.persisted, ConfigFileAccess):
            raise TypeError("Config file cannot be updated.")
        self._updating_config = True
        yield self
        self._updating_config = False
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
    def create_from_arguments(cls, args):
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


class CLIConfig(BaseConfig):

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

    data_dir = Path("Directory path to store blobs.", metavar='DIR')
    download_dir = Path(
        "Directory path to place assembled files downloaded from LBRY.",
        previous_names=['download_directory'], metavar='DIR'
    )
    wallet_dir = Path(
        "Directory containing a 'wallets' subdirectory with 'default_wallet' file.",
        previous_names=['lbryum_wallet_dir'], metavar='DIR'
    )

    share_usage_data = Toggle(
        "Whether to share usage stats and diagnostic info with LBRY.", True,
        previous_names=['upload_log', 'upload_log', 'share_debug_info']
    )

    # claims set to expire within this many blocks will be
    # automatically renewed after startup (if set to 0, renews
    # will not be made automatically)
    auto_renew_claim_height_delta = Integer("", 0)
    cache_time = Integer("", 150)
    data_rate = Float("points/megabyte", .0001)
    delete_blobs_on_remove = Toggle("", True)
    dht_node_port = Integer("", 4444)
    download_timeout = Float("", 30.0)
    blob_download_timeout = Float("", 20.0)
    peer_connect_timeout = Float("", 3.0)
    node_rpc_timeout = Float("", constants.rpc_timeout)
    is_generous_host = Toggle("", True)
    announce_head_blobs_only = Toggle("", True)
    concurrent_announcers = Integer("", 10)
    known_dht_nodes = Servers("", [
        ('lbrynet1.lbry.io', 4444),  # US EAST
        ('lbrynet2.lbry.io', 4444),  # US WEST
        ('lbrynet3.lbry.io', 4444),  # EU
        ('lbrynet4.lbry.io', 4444)  # ASIA
    ])
    max_connections_per_stream = Integer("", 5)
    seek_head_blob_first = Toggle("", True)
    max_key_fee = MaxKeyFee("", {'currency': 'USD', 'amount': 50.0})
    min_info_rate = Float("points/1000 infos", .02)
    min_valuable_hash_rate = Float("points/1000 infos", .05)
    min_valuable_info_rate = Float("points/1000 infos", .05)
    peer_port = Integer("", 3333)
    pointtrader_server = String("", 'http://127.0.0.1:2424')
    reflector_port = Integer("", 5566)
    # if reflect_uploads is True, send files to reflector after publishing (as well as a periodic check in the
    # event the initial upload failed or was disconnected part way through, provided the auto_re_reflect_interval > 0)
    reflect_uploads = Toggle("", True)
    auto_re_reflect_interval = Integer("set to 0 to disable", 86400)
    reflector_servers = Servers("", [
        ('reflector.lbry.io', 5566)
    ])
    run_reflector_server = Toggle("adds reflector to components_to_skip unless True", False)
    sd_download_timeout = Integer("", 3)
    peer_search_timeout = Integer("", 60)
    use_upnp = Toggle("", True)
    use_keyring = Toggle("", False)
    blockchain_name = String("", 'lbrycrd_main')
    lbryum_servers = Servers("", [
        ('lbryumx1.lbry.io', 50001),
        ('lbryumx2.lbry.io', 50001)
    ])
    s3_headers_depth = Integer("download headers from s3 when the local height is more than 10 chunks behind", 96 * 10)
    components_to_skip = Strings("components which will be skipped during start-up of daemon", [])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_default_paths()

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
        cls.data_dir.default, cls.wallet_dir.default, cls.download_dir.default = get_directories()
        cls.config.default = os.path.join(
            self.data_dir, 'daemon_settings.yml'
        )

    @property
    def log_file_path(self):
        return os.path.join(self.data_dir, 'lbrynet.log')


def get_windows_directories() -> typing.Tuple[str, str, str]:
    from lbrynet.winpaths import get_path, FOLDERID, UserHandle

    download_dir = get_path(FOLDERID.Downloads, UserHandle.current)

    # old
    appdata = get_path(FOLDERID.RoamingAppData, UserHandle.current)
    data_dir = os.path.join(appdata, 'lbrynet')
    lbryum_dir = os.path.join(appdata, 'lbryum')
    if os.path.isdir(data_dir) or os.path.isdir(lbryum_dir):
        return data_dir, lbryum_dir, download_dir

    # new
    data_dir = user_data_dir('lbrynet', 'lbry')
    lbryum_dir = user_data_dir('lbryum', 'lbry')
    download_dir = get_path(FOLDERID.Downloads, UserHandle.current)
    return data_dir, lbryum_dir, download_dir


def get_darwin_directories() -> typing.Tuple[str, str, str]:
    data_dir = user_data_dir('LBRY')
    lbryum_dir = os.path.expanduser('~/.lbryum')
    download_dir = os.path.expanduser('~/Downloads')
    return data_dir, lbryum_dir, download_dir


def get_linux_directories() -> typing.Tuple[str, str, str]:
    try:
        with open(os.path.join(user_config_dir(), 'user-dirs.dirs'), 'r') as xdg:
            down_dir = re.search(r'XDG_DOWNLOAD_DIR=(.+)', xdg.read()).group(1)
        down_dir = re.sub('\$HOME', os.getenv('HOME') or os.path.expanduser("~/"), down_dir)
        download_dir = re.sub('\"', '', down_dir)
    except EnvironmentError:
        download_dir = os.getenv('XDG_DOWNLOAD_DIR')
    if not download_dir:
        download_dir = os.path.expanduser('~/Downloads')

    # old
    data_dir = os.path.expanduser('~/.lbrynet')
    lbryum_dir = os.path.expanduser('~/.lbryum')
    if os.path.isdir(data_dir) or os.path.isdir(lbryum_dir):
        return data_dir, lbryum_dir, download_dir

    # new
    return user_data_dir('lbry/lbrynet'), user_data_dir('lbry/lbryum'), download_dir
