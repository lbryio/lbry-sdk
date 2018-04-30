import base58
import json
import logging
import os
import re
import sys
import yaml
import envparse
from appdirs import user_data_dir, user_config_dir
from lbrynet.core import utils
from lbrynet.core.Error import InvalidCurrencyError, NoSuchDirectoryError
from lbrynet.androidhelpers.paths import (
    android_internal_storage_dir,
    android_app_internal_storage_dir
)

try:
    from lbrynet.winhelpers.knownpaths import get_path, FOLDERID, UserHandle
except (ImportError, ValueError, NameError):
    # Android platform: NameError: name 'c_wchar' is not defined
    pass

log = logging.getLogger(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENV_NAMESPACE = 'LBRY_'

LBRYCRD_WALLET = 'lbrycrd'
LBRYUM_WALLET = 'lbryum'
PTC_WALLET = 'ptc'

PROTOCOL_PREFIX = 'lbry'
APP_NAME = 'LBRY'

LINUX = 1
DARWIN = 2
WINDOWS = 3
ANDROID = 4
KB = 2 ** 10
MB = 2 ** 20

DEFAULT_DHT_NODES = [
    ('lbrynet1.lbry.io', 4444),
    ('lbrynet2.lbry.io', 4444),
    ('lbrynet3.lbry.io', 4444)
]

settings_decoders = {
    '.json': json.loads,
    '.yml': yaml.load
}

settings_encoders = {
    '.json': json.dumps,
    '.yml': yaml.safe_dump
}

# set by CLI when the user specifies an alternate config file path
conf_file = None


def _win_path_to_bytes(path):
    """
    Encode Windows paths to string. appdirs.user_data_dir()
    on windows will return unicode path, unlike other platforms
    which returns string. This will cause problems
    because we use strings for filenames and combining them with
    os.path.join() will result in errors.
    """
    for encoding in ('ASCII', 'MBCS'):
        try:
            return path.encode(encoding)
        except (UnicodeEncodeError, LookupError):
            pass
    return path


def _get_old_directories(platform_type):
    directories = {}
    if platform_type == WINDOWS:
        appdata = get_path(FOLDERID.RoamingAppData, UserHandle.current)
        directories['data'] = os.path.join(appdata, 'lbrynet')
        directories['lbryum'] = os.path.join(appdata, 'lbryum')
        directories['download'] = get_path(FOLDERID.Downloads, UserHandle.current)
    elif platform_type == DARWIN:
        directories['data'] = user_data_dir('LBRY')
        directories['lbryum'] = os.path.expanduser('~/.lbryum')
        directories['download'] = os.path.expanduser('~/Downloads')
    elif platform_type == LINUX:
        directories['data'] = os.path.expanduser('~/.lbrynet')
        directories['lbryum'] = os.path.expanduser('~/.lbryum')
        directories['download'] = os.path.expanduser('~/Downloads')
    else:
        raise ValueError('unknown platform value')
    return directories


def _get_new_directories(platform_type):
    directories = {}
    if platform_type == ANDROID:
        directories['data'] = '%s/lbrynet' % android_app_internal_storage_dir()
        directories['lbryum'] = '%s/lbryum' % android_app_internal_storage_dir()
        directories['download'] = '%s/Download' % android_internal_storage_dir()
    elif platform_type == WINDOWS:
        directories['data'] = user_data_dir('lbrynet', 'lbry')
        directories['lbryum'] = user_data_dir('lbryum', 'lbry')
        directories['download'] = get_path(FOLDERID.Downloads, UserHandle.current)
    elif platform_type == DARWIN:
        directories = _get_old_directories(platform_type)
    elif platform_type == LINUX:
        directories['data'] = user_data_dir('lbry/lbrynet')
        directories['lbryum'] = user_data_dir('lbry/lbryum')
        try:
            with open(os.path.join(user_config_dir(), 'user-dirs.dirs'), 'r') as xdg:
                down_dir = re.search(r'XDG_DOWNLOAD_DIR=(.+)', xdg.read()).group(1)
                down_dir = re.sub('\$HOME', os.getenv('HOME'), down_dir)
                directories['download'] = re.sub('\"', '', down_dir)
        except EnvironmentError:
            directories['download'] = os.getenv('XDG_DOWNLOAD_DIR')

        if not directories['download']:
            directories['download'] = os.path.expanduser('~/Downloads')
    else:
        raise ValueError('unknown platform value')
    return directories


if 'ANDROID_ARGUMENT' in os.environ:
    # https://github.com/kivy/kivy/blob/master/kivy/utils.py#L417-L421
    platform = ANDROID
    dirs = _get_new_directories(ANDROID)
elif 'darwin' in sys.platform:
    platform = DARWIN
    dirs = _get_old_directories(DARWIN)
elif 'win' in sys.platform:
    platform = WINDOWS
    if os.path.isdir(_get_old_directories(WINDOWS)['data']) or \
       os.path.isdir(_get_old_directories(WINDOWS)['lbryum']):
        dirs = _get_old_directories(WINDOWS)
    else:
        dirs = _get_new_directories(WINDOWS)
    dirs['data'] = _win_path_to_bytes(dirs['data'])
    dirs['lbryum'] = _win_path_to_bytes(dirs['lbryum'])
    dirs['download'] = _win_path_to_bytes(dirs['download'])
else:
    platform = LINUX
    if os.path.isdir(_get_old_directories(LINUX)['data']) or \
       os.path.isdir(_get_old_directories(LINUX)['lbryum']):
        dirs = _get_old_directories(LINUX)
    else:
        dirs = _get_new_directories(LINUX)

default_data_dir = dirs['data']
default_lbryum_dir = dirs['lbryum']
default_download_dir = dirs['download']

ICON_PATH = 'icons' if platform is WINDOWS else 'app.icns'


def server_port(server_and_port):
    server, port = server_and_port.split(':')
    return server, int(port)


def server_list(servers):
    return [server_port(server) for server in servers]


class Env(envparse.Env):
    """An Env parser that automatically namespaces the variables with LBRY"""

    def __init__(self, **schema):
        self.original_schema = schema
        my_schema = {
            self._convert_key(key): self._convert_value(value)
            for key, value in schema.items()
            }
        envparse.Env.__init__(self, **my_schema)

    def __call__(self, key, *args, **kwargs):
        my_key = self._convert_key(key)
        return super(Env, self).__call__(my_key, *args, **kwargs)

    @staticmethod
    def _convert_key(key):
        return ENV_NAMESPACE + key.upper()

    @staticmethod
    def _convert_value(value):
        """ Allow value to be specified as a tuple or list.

        If you do this, the tuple/list must be of the
        form (cast, default) or (cast, default, subcast)
        """

        if isinstance(value, (tuple, list)):
            new_value = {'cast': value[0], 'default': value[1]}
            if len(value) == 3:
                new_value['subcast'] = value[2]
            return new_value
        return value


TYPE_DEFAULT = 'default'
TYPE_PERSISTED = 'persisted'
TYPE_ENV = 'env'
TYPE_CLI = 'cli'
TYPE_RUNTIME = 'runtime'

FIXED_SETTINGS = {
    'ANALYTICS_ENDPOINT': 'https://api.segment.io/v1',
    'ANALYTICS_TOKEN': 'Ax5LZzR1o3q3Z3WjATASDwR5rKyHH0qOIRIbLmMXn2H=',
    'API_ADDRESS': 'lbryapi',
    'APP_NAME': APP_NAME,
    'BLOBFILES_DIR': 'blobfiles',
    'CRYPTSD_FILE_EXTENSION': '.cryptsd',
    'CURRENCIES': {
        'BTC': {'type': 'crypto'},
        'LBC': {'type': 'crypto'},
        'USD': {'type': 'fiat'},
    },
    'DB_REVISION_FILE_NAME': 'db_revision',
    'ICON_PATH': ICON_PATH,
    'LOGGLY_TOKEN': 'BQEzZmMzLJHgAGxkBF00LGD0YGuyATVgAmqxAQEuAQZ2BQH4',
    'LOG_FILE_NAME': 'lbrynet.log',
    'LOG_POST_URL': 'https://lbry.io/log-upload',
    'MAX_BLOB_REQUEST_SIZE': 64 * KB,
    'MAX_HANDSHAKE_SIZE': 64 * KB,
    'MAX_REQUEST_SIZE': 64 * KB,
    'MAX_RESPONSE_INFO_SIZE': 64 * KB,
    'MAX_BLOB_INFOS_TO_REQUEST': 20,
    'PROTOCOL_PREFIX': PROTOCOL_PREFIX,
    'SLACK_WEBHOOK': ('nUE0pUZ6Yl9bo29epl5moTSwnl5wo20ip2IlqzywMKZiIQSFZR5'
                      'AHx4mY0VmF0WQZ1ESEP9kMHZlp1WzJwWOoKN3ImR1M2yUAaMyqGZ='),
    'WALLET_TYPES': [LBRYUM_WALLET, LBRYCRD_WALLET],
}

ADJUSTABLE_SETTINGS = {
    # By default, daemon will block all cross origin requests
    # but if this is set, this value will be used for the
    # Access-Control-Allow-Origin. For example
    # set to '*' to allow all requests, or set to 'http://localhost:8080'
    # if you're running a test UI on that port
    'allowed_origin': (str, ''),

    # Changing this value is not-advised as it could potentially
    # expose the lbrynet daemon to the outside world which would
    # give an attacker access to your wallet and you could lose
    # all of your credits.
    'api_host': (str, 'localhost'),
    'api_port': (int, 5279),
    # claims set to expire within this many blocks will be
    # automatically renewed after startup (if set to 0, renews
    # will not be made automatically)
    'auto_renew_claim_height_delta': (int, 0),
    'cache_time': (int, 150),
    'data_dir': (str, default_data_dir),
    'data_rate': (float, .0001),  # points/megabyte
    'delete_blobs_on_remove': (bool, True),
    'dht_node_port': (int, 4444),
    'download_directory': (str, default_download_dir),
    'download_timeout': (int, 180),
    'is_generous_host': (bool, True),
    'announce_head_blobs_only': (bool, True),
    'known_dht_nodes': (list, DEFAULT_DHT_NODES, server_list),
    'lbryum_wallet_dir': (str, default_lbryum_dir),
    'max_connections_per_stream': (int, 5),
    'seek_head_blob_first': (bool, True),
    # TODO: writing json on the cmd line is a pain, come up with a nicer
    # parser for this data structure. maybe 'USD:25'
    'max_key_fee': (json.loads, {'currency': 'USD', 'amount': 50.0}),
    'disable_max_key_fee': (bool, False),
    'min_info_rate': (float, .02),  # points/1000 infos
    'min_valuable_hash_rate': (float, .05),  # points/1000 infos
    'min_valuable_info_rate': (float, .05),  # points/1000 infos
    'peer_port': (int, 3333),
    'pointtrader_server': (str, 'http://127.0.0.1:2424'),
    'reflector_port': (int, 5566),
    # if reflect_uploads is True, send files to reflector (after publishing as well as a
    # periodic check in the event the initial upload failed or was disconnected part way through
    'reflect_uploads': (bool, True),
    'auto_re_reflect_interval': (int, 3600),
    'reflector_servers': (list, [('reflector2.lbry.io', 5566)], server_list),
    'run_reflector_server': (bool, False),
    'sd_download_timeout': (int, 3),
    'share_usage_data': (bool, True),  # whether to share usage stats and diagnostic info with LBRY
    'peer_search_timeout': (int, 3),
    'use_auth_http': (bool, False),
    'use_upnp': (bool, True),
    'use_keyring': (bool, False),
    'wallet': (str, LBRYUM_WALLET),
    'blockchain_name': (str, 'lbrycrd_main'),
    'lbryum_servers': (list, [('lbryum8.lbry.io', 50001), ('lbryum9.lbry.io', 50001)], server_list),
    's3_headers_depth': (int, 96 * 10)   # download headers from s3 when the local height is more than 10 chunks behind
}


class Config(object):
    def __init__(self, fixed_defaults, adjustable_defaults, persisted_settings=None,
                 environment=None, cli_settings=None):

        self._installation_id = None
        self._session_id = base58.b58encode(utils.generate_id())
        self._node_id = None

        self._fixed_defaults = fixed_defaults
        self._adjustable_defaults = adjustable_defaults

        self._data = {
            TYPE_DEFAULT: {},  # defaults
            TYPE_PERSISTED: {},  # stored settings from daemon_settings.yml (or from a db, etc)
            TYPE_ENV: {},  # settings from environment variables
            TYPE_CLI: {},  # command-line arguments
            TYPE_RUNTIME: {},  # set during runtime (using self.set(), etc)
        }

        # the order in which a piece of data is searched for. earlier types override later types
        self._search_order = (
            TYPE_RUNTIME, TYPE_CLI, TYPE_ENV, TYPE_PERSISTED, TYPE_DEFAULT
        )

        # types of data where user specified config values can be stored
        self._user_specified = (
            TYPE_RUNTIME, TYPE_CLI, TYPE_ENV, TYPE_PERSISTED
        )

        self._data[TYPE_DEFAULT].update(self._fixed_defaults)
        self._data[TYPE_DEFAULT].update(
            {k: v[1] for (k, v) in self._adjustable_defaults.iteritems()})

        if persisted_settings is None:
            persisted_settings = {}
        self._validate_settings(persisted_settings)
        self._data[TYPE_PERSISTED].update(persisted_settings)

        env_settings = self._parse_environment(environment)
        self._validate_settings(env_settings)
        self._data[TYPE_ENV].update(env_settings)

        if cli_settings is None:
            cli_settings = {}
        self._validate_settings(cli_settings)
        self._data[TYPE_CLI].update(cli_settings)

    def __repr__(self):
        return self.get_current_settings_dict().__repr__()

    def __iter__(self):
        for k in self._data[TYPE_DEFAULT].iterkeys():
            yield k

    def __getitem__(self, name):
        return self.get(name)

    def __setitem__(self, name, value):
        return self.set(name, value)

    def __contains__(self, name):
        return name in self._data[TYPE_DEFAULT]

    @staticmethod
    def _parse_environment(environment):
        env_settings = {}
        if environment is not None:
            assert isinstance(environment, Env)
            for opt in environment.original_schema:
                if environment(opt) is not None:
                    env_settings[opt] = environment(opt)
        return env_settings

    def _assert_valid_data_type(self, data_type):
        if data_type not in self._data:
            raise KeyError('{} in is not a valid data type'.format(data_type))

    def get_valid_setting_names(self):
        return self._data[TYPE_DEFAULT].keys()

    def _is_valid_setting(self, name):
        return name in self.get_valid_setting_names()

    def _assert_valid_setting(self, name):
        if not self._is_valid_setting(name):
            raise KeyError('{} is not a valid setting'.format(name))

    def _validate_settings(self, data):
        invalid_settings = set(data.keys()) - set(self.get_valid_setting_names())
        if len(invalid_settings) > 0:
            raise KeyError('invalid settings: {}'.format(', '.join(invalid_settings)))

    def _assert_editable_setting(self, name):
        self._assert_valid_setting(name)
        if name in self._fixed_defaults:
            raise ValueError('{} is not an editable setting'.format(name))

    def _assert_valid_setting_value(self, name, value):
        if name == "max_key_fee":
            currency = str(value["currency"]).upper()
            if currency not in self._fixed_defaults['CURRENCIES'].keys():
                raise InvalidCurrencyError(currency)
        elif name == "download_directory":
            directory = str(value)
            if not os.path.exists(directory):
                raise NoSuchDirectoryError(directory)

    def is_default(self, name):
        """Check if a config value is wasn't specified by the user

        Args:
            name: the name of the value to check

        Returns: true if config value is the default one, false if it was specified by
        the user

        Sometimes it may be helpful to understand if a config value was specified
        by the user or if it still holds its default value. This function will return
        true when the config value is still the default. Note that when the user
        specifies a value that is equal to the default one, it will still be considered
        as 'user specified'
        """

        self._assert_valid_setting(name)
        for possible_data_type in self._user_specified:
            if name in self._data[possible_data_type]:
                return False
        return True

    def get(self, name, data_type=None):
        """Get a config value

        Args:
            name: the name of the value to get
            data_type: if given, get the value from a specific data set (see below)

        Returns: the config value for the given name

        If data_type is None, get() will search for the given name in each data set, in
        order of precedence. It will return the first value it finds. This is the "effective"
        value of a config name. For example, ENV values take precedence over DEFAULT values,
        so if a value is present in ENV and in DEFAULT, the ENV value will be returned
        """
        self._assert_valid_setting(name)
        if data_type is not None:
            self._assert_valid_data_type(data_type)
            return self._data[data_type][name]
        for possible_data_type in self._search_order:
            if name in self._data[possible_data_type]:
                return self._data[possible_data_type][name]
        raise KeyError('{} is not a valid setting'.format(name))

    def set(self, name, value, data_types=(TYPE_RUNTIME,)):
        """Set a config value

        Args:
            name: the name of the value to set
            value: the value
            data_types: what type(s) of data this is

        Returns: None

        By default, this sets the RUNTIME value of a config. If you wish to set other
        data types (e.g. PERSISTED values to save to a file, CLI values from parsed
        command-line options, etc), you can specify that with the data_types param
        """
        self._assert_editable_setting(name)
        self._assert_valid_setting_value(name, value)

        for data_type in data_types:
            self._assert_valid_data_type(data_type)
            self._data[data_type][name] = value

    def update(self, updated_settings, data_types=(TYPE_RUNTIME,)):
        for k, v in updated_settings.iteritems():
            try:
                self.set(k, v, data_types=data_types)
            except (KeyError, AssertionError):
                pass

    def get_current_settings_dict(self):
        current_settings = {}
        for key in self.get_valid_setting_names():
            current_settings[key] = self.get(key)
        return current_settings

    def get_adjustable_settings_dict(self):
        return {
            key: val for key, val in self.get_current_settings_dict().iteritems()
            if key in self._adjustable_defaults
            }

    def save_conf_file_settings(self):
        if conf_file:
            path = conf_file
        else:
            path = self.get_conf_filename()

        ext = os.path.splitext(path)[1]
        encoder = settings_encoders.get(ext, False)
        assert encoder is not False, 'Unknown settings format %s' % ext
        with open(path, 'w') as settings_file:
            settings_file.write(encoder(self._data[TYPE_PERSISTED]))

    @staticmethod
    def _convert_conf_file_lists(decoded):
        converted = {}
        for k, v in decoded.iteritems():
            if k in ADJUSTABLE_SETTINGS and len(ADJUSTABLE_SETTINGS[k]) == 3:
                converted[k] = ADJUSTABLE_SETTINGS[k][2](v)
            else:
                converted[k] = v
        return converted

    def initialize_post_conf_load(self):
        settings.installation_id = settings.get_installation_id()
        settings.node_id = settings.get_node_id()

    def load_conf_file_settings(self):
        if conf_file:
            path = conf_file
        else:
            path = self.get_conf_filename()

        ext = os.path.splitext(path)[1]
        decoder = settings_decoders.get(ext, False)
        assert decoder is not False, 'Unknown settings format %s' % ext
        try:
            with open(path, 'r') as settings_file:
                data = settings_file.read()
            decoded = self._fix_old_conf_file_settings(decoder(data))
            log.info('Loaded settings file: %s', path)
            self._validate_settings(decoded)
            self._data[TYPE_PERSISTED].update(self._convert_conf_file_lists(decoded))
        except (IOError, OSError) as err:
            log.info('%s: Failed to update settings from %s', err, path)

        #initialize members depending on config file
        self.initialize_post_conf_load()

    def _fix_old_conf_file_settings(self, settings_dict):
        if 'API_INTERFACE' in settings_dict:
            settings_dict['api_host'] = settings_dict['API_INTERFACE']
            del settings_dict['API_INTERFACE']
        if 'startup_scripts' in settings_dict:
            del settings_dict['startup_scripts']
        if 'upload_log' in settings_dict:
            settings_dict['share_usage_data'] = settings_dict['upload_log']
            del settings_dict['upload_log']
        if 'share_debug_info' in settings_dict:
            settings_dict['share_usage_data'] = settings_dict['share_debug_info']
            del settings_dict['share_debug_info']
        for key in settings_dict.keys():
            if not self._is_valid_setting(key):
                log.warning('Ignoring invalid conf file setting: %s', key)
                del settings_dict[key]
        return settings_dict

    def ensure_data_dir(self):
        # although there is a risk of a race condition here we don't
        # expect there to be multiple processes accessing this
        # directory so the risk can be ignored
        if not os.path.isdir(self['data_dir']):
            os.makedirs(self['data_dir'])
        return self['data_dir']

    def get_log_filename(self):
        """
        Return the log file for this platform.
        Also ensure the containing directory exists.
        """
        return os.path.join(self.ensure_data_dir(), self['LOG_FILE_NAME'])

    def get_api_connection_string(self):
        return 'http://%s:%i/%s' % (self['api_host'], self['api_port'], self['API_ADDRESS'])

    def get_ui_address(self):
        return 'http://%s:%i' % (self['api_host'], self['api_port'])

    def get_db_revision_filename(self):
        return os.path.join(self.ensure_data_dir(), self['DB_REVISION_FILE_NAME'])

    def get_conf_filename(self):
        data_dir = self.ensure_data_dir()
        yml_path = os.path.join(data_dir, 'daemon_settings.yml')
        json_path = os.path.join(data_dir, 'daemon_settings.json')
        if os.path.isfile(yml_path):
            return yml_path
        elif os.path.isfile(json_path):
            return json_path
        else:
            return yml_path

    def get_installation_id(self):
        install_id_filename = os.path.join(self.ensure_data_dir(), "install_id")
        if not self._installation_id:
            if os.path.isfile(install_id_filename):
                with open(install_id_filename, "r") as install_id_file:
                    self._installation_id = str(install_id_file.read()).strip()
        if not self._installation_id:
            self._installation_id = base58.b58encode(utils.generate_id())
            with open(install_id_filename, "w") as install_id_file:
                install_id_file.write(self._installation_id)
        return self._installation_id

    def get_node_id(self):
        node_id_filename = os.path.join(self.ensure_data_dir(), "node_id")
        if not self._node_id:
            if os.path.isfile(node_id_filename):
                with open(node_id_filename, "r") as node_id_file:
                    self._node_id = base58.b58decode(str(node_id_file.read()).strip())
        if not self._node_id:
            self._node_id = utils.generate_id()
            with open(node_id_filename, "w") as node_id_file:
                node_id_file.write(base58.b58encode(self._node_id))
        return self._node_id

    def get_session_id(self):
        return self._session_id


# type: Config
settings = None


def get_default_env():
    env_defaults = {}
    for k, v in ADJUSTABLE_SETTINGS.iteritems():
        if len(v) == 3:
            env_defaults[k] = (v[0], None, v[2])
        else:
            env_defaults[k] = (v[0], None)
    return Env(**env_defaults)


def initialize_settings(load_conf_file=True):
    global settings
    if settings is None:
        settings = Config(FIXED_SETTINGS, ADJUSTABLE_SETTINGS,
                          environment=get_default_env())
        if load_conf_file:
            settings.load_conf_file_settings()
