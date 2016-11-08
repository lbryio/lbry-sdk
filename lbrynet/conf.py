import copy
import json
import logging
import os
import sys
import yaml

from appdirs import user_data_dir


log = logging.getLogger(__name__)


LINUX = 1
DARWIN = 2
WINDOWS = 3
KB = 2**10
MB = 2**20


if sys.platform.startswith("darwin"):
    platform = DARWIN
    default_download_directory = os.path.join(os.path.expanduser("~"), 'Downloads')
    default_data_dir = user_data_dir("LBRY")
    default_lbryum_dir = os.path.join(os.path.expanduser("~"), ".lbryum")
elif sys.platform.startswith("win"):
    platform = WINDOWS
    from lbrynet.winhelpers.knownpaths import get_path, FOLDERID, UserHandle
    default_download_directory = get_path(FOLDERID.Downloads, UserHandle.current)
    default_data_dir = os.path.join(
        get_path(FOLDERID.RoamingAppData, UserHandle.current), "lbrynet")
    default_lbryum_dir = os.path.join(
        get_path(FOLDERID.RoamingAppData, UserHandle.current), "lbryum")
else:
    platform = LINUX
    default_download_directory = os.path.join(os.path.expanduser("~"), 'Downloads')
    default_data_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
    default_lbryum_dir = os.path.join(os.path.expanduser("~"), ".lbryum")


def convert_setting(env_val, current_val):
    try:
        return _convert_setting(env_val, current_val)
    except Exception as exc:
        log.warning(
            'Failed to convert %s. Returning original: %s: %s',
            env_val, current_val, exc)
        return current_val


def _convert_setting(env_val, current_val):
    new_type = env_val.__class__
    current_type = current_val.__class__
    if current_type is bool:
        if new_type is bool:
            return env_val
        elif str(env_val).lower() == "false":
            return False
        elif str(env_val).lower() == "true":
            return True
        else:
            raise ValueError('{} is not a valid boolean value'.format(env_val))
    elif current_type is int:
        return int(env_val)
    elif current_type is float:
        return float(env_val)
    elif current_type is str:
        return str(env_val)
    elif current_type is unicode:
        return unicode(env_val)
    elif current_type is dict:
        return dict(env_val)
    elif current_type is list:
        return list(env_val)
    elif current_type is tuple:
        return tuple(env_val)
    else:
        raise ValueError('Type {} cannot be converted'.format(current_type))


def convert_env_setting(setting, value):
    try:
        env_val = os.environ[setting]
    except KeyError:
        return value
    else:
        return convert_setting(env_val, value)


def get_env_settings(settings):
    for setting, value in settings.iteritems():
        setting = 'LBRY_' + setting.upper()
        yield convert_env_setting(setting, value)


def add_env_settings_to_dict(settings_dict):
    for setting, env_setting in zip(settings_dict, get_env_settings(settings_dict)):
        settings_dict.update({setting: env_setting})
    return settings_dict


class Setting(object):
    """A collection of configuration settings"""
    __fixed = []
    __excluded = ['get_dict', 'update']

    def __iter__(self):
        for k in self.__dict__.iterkeys():
            if k.startswith('_') or k in self.__excluded:
                continue
            yield k

    def __getitem__(self, item):
        assert item in self, IndexError
        return self.__dict__[item]

    def __setitem__(self, key, value):
        assert key in self and key not in self.__fixed, KeyError(key)
        old_value = self[key]
        new_value = convert_setting(value, old_value)
        self.__dict__[key] = new_value

    def __contains__(self, item):
        return item in iter(self)

    def get_dict(self):
        return {k: self[k] for k in self}

    def update(self, other):
        for k, v in other.iteritems():
            try:
                self.__setitem__(k, v)
            except (KeyError, AssertionError):
                pass


class AdjustableSettings(Setting):
    """Settings that are allowed to be overriden by the user"""
    def __init__(self):
        self.is_generous_host = True
        self.run_on_startup = False
        self.download_directory = default_download_directory
        self.max_upload = 0.0
        self.max_download = 0.0
        self.upload_log = True
        self.delete_blobs_on_remove = True
        self.use_upnp = True
        self.start_lbrycrdd = True
        self.run_reflector_server = False
        self.startup_scripts = []
        self.last_version = {'lbrynet': '0.0.1', 'lbryum': '0.0.1'}
        self.peer_port = 3333
        self.dht_node_port = 4444
        self.reflector_port = 5566
        self.download_timeout = 30
        self.max_search_results = 25
        self.search_timeout = 3.0
        self.cache_time = 150
        self.host_ui = True
        self.check_ui_requirements = True
        self.local_ui_path = False
        self.api_port = 5279
        self.search_servers = ['lighthouse1.lbry.io:50005']
        self.data_rate = .0001  # points/megabyte
        self.min_info_rate = .02  # points/1000 infos
        self.min_valuable_info_rate = .05  # points/1000 infos
        self.min_valuable_hash_rate = .05  # points/1000 infos
        self.max_connections_per_stream = 5
        self.known_dht_nodes = [
            ('104.236.42.182', 4000),
            ('lbrynet1.lbry.io', 4444),
            ('lbrynet2.lbry.io', 4444),
            ('lbrynet3.lbry.io', 4444)
        ]
        self.pointtrader_server = 'http://127.0.0.1:2424'
        self.reflector_servers = [("reflector.lbry.io", 5566)]
        self.wallet = "lbryum"
        self.ui_branch = "master"
        self.default_ui_branch = 'master'
        self.data_dir = default_data_dir
        self.lbryum_wallet_dir = default_lbryum_dir
        self.use_auth_http = False
        self.sd_download_timeout = 3
        self.max_key_fee = {'USD': {'amount': 25.0, 'address': ''}}


class ApplicationSettings(Setting):
    """Settings that are constants and shouldn't be overriden"""
    def __init__(self):
        self.MAX_HANDSHAKE_SIZE = 64*KB
        self.MAX_REQUEST_SIZE = 64*KB
        self.MAX_BLOB_REQUEST_SIZE = 64*KB
        self.MAX_RESPONSE_INFO_SIZE = 64*KB
        self.MAX_BLOB_INFOS_TO_REQUEST = 20
        self.BLOBFILES_DIR = "blobfiles"
        self.BLOB_SIZE = 2*MB
        self.LOG_FILE_NAME = "lbrynet.log"
        self.LOG_POST_URL = "https://lbry.io/log-upload"
        self.CRYPTSD_FILE_EXTENSION = ".cryptsd"
        self.API_INTERFACE = "localhost"
        self.API_ADDRESS = "lbryapi"
        self.ICON_PATH = "icons" if platform is WINDOWS else "app.icns"
        self.APP_NAME = "LBRY"
        self.PROTOCOL_PREFIX = "lbry"
        self.WALLET_TYPES = ["lbryum", "lbrycrd"]
        self.SOURCE_TYPES = ['lbry_sd_hash', 'url', 'btih']
        self.CURRENCIES = {
            'BTC': {'type': 'crypto'},
            'LBC': {'type': 'crypto'},
            'USD': {'type': 'fiat'},
        }
        self.LOGGLY_TOKEN = 'LJEzATH4AzRgAwxjAP00LwZ2YGx3MwVgZTMuBQZ3MQuxLmOv'
        self.ANALYTICS_ENDPOINT = 'https://api.segment.io/v1'
        self.ANALYTICS_TOKEN = 'Ax5LZzR1o3q3Z3WjATASDwR5rKyHH0qOIRIbLmMXn2H='


APPLICATION_SETTINGS = AdjustableSettings()
ADJUSTABLE_SETTINGS = AdjustableSettings()


class DefaultSettings(ApplicationSettings, AdjustableSettings):
    __fixed = APPLICATION_SETTINGS.get_dict().keys()

    def __init__(self):
        ApplicationSettings.__init__(self)
        AdjustableSettings.__init__(self)


DEFAULT_SETTINGS = DefaultSettings()


class Config(DefaultSettings):
    __shared_state = copy.deepcopy(DEFAULT_SETTINGS.get_dict())

    def __init__(self):
        self.__dict__ = add_env_settings_to_dict(self.__shared_state)

    @property
    def ORIGIN(self):
        return "http://%s:%i" % (DEFAULT_SETTINGS.API_INTERFACE, self.api_port)

    @property
    def REFERER(self):
        return "http://%s:%i/" % (DEFAULT_SETTINGS.API_INTERFACE, self.api_port)

    @property
    def API_CONNECTION_STRING(self):
        return "http://%s:%i/%s" % (
            DEFAULT_SETTINGS.API_INTERFACE, self.api_port, DEFAULT_SETTINGS.API_ADDRESS)

    @property
    def UI_ADDRESS(self):
        return "http://%s:%i" % (DEFAULT_SETTINGS.API_INTERFACE, self.api_port)

    def ensure_data_dir(self):
        # although there is a risk of a race condition here we don't
        # expect there to be multiple processes accessing this
        # directory so the risk can be ignored
        if not os.path.isdir(self.data_dir):
            os.makedirs(self.data_dir)
        return self.data_dir

    def get_log_filename(self):
        """Return the log file for this platform.

        Also ensure the containing directory exists
        """
        return os.path.join(self.ensure_data_dir(), self.LOG_FILE_NAME)

    def get_conf_filename(self):
        return os.path.join(self.ensure_data_dir(), "daemon_settings.yml")


def update_settings_from_file(filename=None):
    filename = filename or settings.get_conf_filename()
    try:
        updates = load_settings(filename)
        log.info("Loaded settings file: %s", updates)
        settings.update(updates)
    except (IOError, OSError) as ex:
        log.info('%s: Failed to update settings from %s', ex, filename)


settings_decoders = {
    '.json': json.loads,
    '.yml': yaml.load
}

settings_encoders = {
    '.json': json.dumps,
    '.yml': yaml.safe_dump
}


def load_settings(path):
    ext = os.path.splitext(path)[1]
    with open(path, 'r') as settings_file:
        data = settings_file.read()
    decoder = settings_decoders.get(ext, False)
    assert decoder is not False, "Unknown settings format .%s" % ext
    return decoder(data)


# TODO: be careful with this. If a setting is overriden by an environment variable
# or command line flag we don't want to persist it for future settings.
def save_settings(path=None):
    path = path or settings.get_conf_filename()
    to_save = {k: v for k, v in settings.__dict__.iteritems() if k in ADJUSTABLE_SETTINGS}
    ext = os.path.splitext(path)[1]
    encoder = settings_encoders.get(ext, False)
    assert encoder is not False, "Unknown settings format .%s" % ext
    with open(path, 'w') as settings_file:
        settings_file.write(encoder(to_save))


# TODO: don't load the configuration automatically. The configuration
#       should be loaded at runtime, not at module import time. Module
#       import should have no side-effects. This is also bad because
#       it means that settings are read from the environment even for
#       tests, which is rarely what you want to happen.
settings = Config()
