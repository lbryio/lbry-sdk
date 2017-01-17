import base58
import json
import logging
import os
import sys
import yaml
import envparse
from appdirs import user_data_dir
from lbrynet.core import utils

log = logging.getLogger(__name__)

ENV_NAMESPACE = 'LBRY_'

LBRYCRD_WALLET = 'lbrycrd'
LBRYUM_WALLET = 'lbryum'
PTC_WALLET = 'ptc'

PROTOCOL_PREFIX = 'lbry'
APP_NAME = 'LBRY'

LINUX = 1
DARWIN = 2
WINDOWS = 3
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

if sys.platform.startswith('darwin'):
    platform = DARWIN
    default_download_directory = os.path.join(os.path.expanduser('~'), 'Downloads')
    default_data_dir = user_data_dir('LBRY')
    default_lbryum_dir = os.path.join(os.path.expanduser('~'), '.lbryum')
elif sys.platform.startswith('win'):
    platform = WINDOWS
    from lbrynet.winhelpers.knownpaths import get_path, FOLDERID, UserHandle

    default_download_directory = get_path(FOLDERID.Downloads, UserHandle.current)
    default_data_dir = os.path.join(
        get_path(FOLDERID.RoamingAppData, UserHandle.current), 'lbrynet')
    default_lbryum_dir = os.path.join(
        get_path(FOLDERID.RoamingAppData, UserHandle.current), 'lbryum')
else:
    platform = LINUX
    default_download_directory = os.path.join(os.path.expanduser('~'), 'Downloads')
    default_data_dir = os.path.join(os.path.expanduser('~'), '.lbrynet')
    default_lbryum_dir = os.path.join(os.path.expanduser('~'), '.lbryum')

ICON_PATH = 'icons' if platform is WINDOWS else 'app.icns'


def server_port(server_and_port):
    server, port = server_and_port.split(':')
    return server, int(port)


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
        """
        Allow value to be specified as a tuple or list. If you do this, the tuple/list
        must be of the form (cast, default) or (cast, default, subcast)
        """
        if isinstance(value, (tuple, list)):
            new_value = {'cast': value[0], 'default': value[1]}
            if len(value) == 3:
                new_value['subcast'] = value[2]
            return new_value
        return value


FIXED_SETTINGS = {
    'ANALYTICS_ENDPOINT': 'https://api.segment.io/v1',
    'ANALYTICS_TOKEN': 'Ax5LZzR1o3q3Z3WjATASDwR5rKyHH0qOIRIbLmMXn2H=',
    'API_ADDRESS': 'lbryapi',
    'APP_NAME': APP_NAME,
    'BLOBFILES_DIR': 'blobfiles',
    'BLOB_SIZE': 2 * MB,
    'CRYPTSD_FILE_EXTENSION': '.cryptsd',
    'CURRENCIES': {
        'BTC': {'type': 'crypto'},
        'LBC': {'type': 'crypto'},
        'USD': {'type': 'fiat'},
    },
    'DB_REVISION_FILE_NAME': 'db_revision',
    'ICON_PATH': ICON_PATH,
    'LOGGLY_TOKEN': 'LJEzATH4AzRgAwxjAP00LwZ2YGx3MwVgZTMuBQZ3MQuxLmOv',
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
    'SOURCE_TYPES': ['lbry_sd_hash', 'url', 'btih'],
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
    'bittrex_feed': (str, 'https://bittrex.com/api/v1.1/public/getmarkethistory'),
    'cache_time': (int, 150),
    'check_ui_requirements': (bool, True),
    'data_dir': (str, default_data_dir),
    'data_rate': (float, .0001),  # points/megabyte
    'default_ui_branch': (str, 'master'),
    'delete_blobs_on_remove': (bool, True),
    'dht_node_port': (int, 4444),
    'download_directory': (str, default_download_directory),
    'download_timeout': (int, 30),
    'host_ui': (bool, True),
    'is_generous_host': (bool, True),
    'known_dht_nodes': (list, DEFAULT_DHT_NODES, server_port),

    # TODO: this should not be configured; move it elsewhere
    'last_version': (dict, {'lbrynet': '0.0.1', 'lbryum': '0.0.1'}),

    'lbryum_wallet_dir': (str, default_lbryum_dir),
    'local_ui_path': (str, ''),
    'max_connections_per_stream': (int, 5),
    'max_download': (float, 0.0),

    # TODO: this field is more complicated than it needs to be because
    # it goes through a Fee validator when loaded by the exchange rate
    # manager.  Look into refactoring the exchange rate conversion to
    # take in a simpler form.
    #
    # TODO: writing json on the cmd line is a pain, come up with a nicer
    # parser for this data structure. (maybe MAX_KEY_FEE': USD:25
    'max_key_fee': (json.loads, {'USD': {'amount': 25.0, 'address': ''}}),

    'max_search_results': (int, 25),
    'max_upload': (float, 0.0),
    'min_info_rate': (float, .02),  # points/1000 infos
    'min_valuable_hash_rate': (float, .05),  # points/1000 infos
    'min_valuable_info_rate': (float, .05),  # points/1000 infos
    'peer_port': (int, 3333),
    'pointtrader_server': (str, 'http://127.0.0.1:2424'),
    'reflector_port': (int, 5566),
    'reflector_reupload': (bool, True),
    'reflector_servers': (list, [('reflector.lbry.io', 5566)], server_port),
    'run_on_startup': (bool, False),
    'run_reflector_server': (bool, False),
    'sd_download_timeout': (int, 3),
    'search_servers': (list, ['lighthouse1.lbry.io:50005']),
    'search_timeout': (float, 5.0),
    'startup_scripts': (list, []),
    'ui_branch': (str, 'master'),
    'upload_log': (bool, True),
    'use_auth_http': (bool, False),
    'use_upnp': (bool, True),
    'wallet': (str, LBRYUM_WALLET),
}


class Config:
    def __init__(self, fixed_defaults, adjustable_defaults, conf_file_settings={}, environment=None,
                 cli_settings={}):
        self._lbry_id = None
        self._session_id = base58.b58encode(utils.generate_id())

        self.__fixed = fixed_defaults
        self.__adjustable = adjustable_defaults

        self._init_defaults()
        self.conf_file_settings = conf_file_settings  # from daemon_settings.yml
        self.env_settings = self._parse_environment(environment)  # from environment variables
        self.cli_settings = cli_settings  # from command_line flags/args
        self.runtime_settings = {}  # set by self.set() during runtime
        self._assert_valid_settings()
        self._combine_settings()

    def __repr__(self):
        return self.combined_settings.__repr__()

    def __iter__(self):
        for k in self.combined_settings.iterkeys():
            yield k

    def __getitem__(self, name):
        return self.get(name)

    def __setitem__(self, name, value):
        return self.set(name, value)

    def __contains__(self, name):
        return name in self.combined_settings

    def _parse_environment(self, environment):
        env_settings = {}
        if environment is None:
            environment = Env(**self.__adjustable)
        if environment:
            assert isinstance(environment, Env)
            for opt in environment.original_schema:
                env_settings[opt] = environment(opt)
        return env_settings

    def _init_defaults(self):
        self.defaults = self.__fixed.copy()
        for k, v in self.__adjustable.iteritems():
            self.defaults[k] = v[1]

    def _assert_valid_settings(self):
        for s in [self.conf_file_settings, self.env_settings, self.cli_settings,
                  self.runtime_settings]:
            for name in s:
                assert name in self.defaults, IndexError('%s is not a valid setting' % name)

    def _combine_settings(self):
        self.combined_settings = {}
        for s in [self.defaults, self.conf_file_settings, self.env_settings, self.cli_settings,
                  self.runtime_settings]:
            self.combined_settings.update(s)

    def get(self, name):
        assert name in self.defaults, IndexError('%s is not a valid setting' % name)
        return self.combined_settings[name]

    def set(self, name, value, set_conf_setting=False):
        assert name in self.defaults and name not in self.__fixed, KeyError
        self.runtime_settings[name] = value
        if set_conf_setting:
            self.conf_file_settings[name] = value
        self._combine_settings()

    def set_cli_settings(self, cli_settings):
        self.cli_settings = cli_settings
        self._assert_valid_settings()
        self._combine_settings()

    def update(self, updated_settings, set_conf_setting=False):
        for k, v in updated_settings.iteritems():
            try:
                self.set(k, v, set_conf_setting=set_conf_setting)
            except (KeyError, AssertionError):
                pass

    def get_current_settings_dict(self):
        return self.combined_settings

    def get_adjustable_settings_dict(self):
        return {
            opt: val for opt, val in self.get_current_settings_dict().iteritems()
            if opt in self.__adjustable
            }

    def save_conf_file_settings(self):
        path = self.get_conf_filename()
        ext = os.path.splitext(path)[1]
        encoder = settings_encoders.get(ext, False)
        assert encoder is not False, 'Unknown settings format .%s' % ext
        with open(path, 'w') as settings_file:
            settings_file.write(encoder(self.conf_file_settings))

    def load_conf_file_settings(self):
        path = self.get_conf_filename()
        ext = os.path.splitext(path)[1]
        decoder = settings_decoders.get(ext, False)
        assert decoder is not False, 'Unknown settings format .%s' % ext
        try:
            with open(path, 'r') as settings_file:
                data = settings_file.read()
            decoded = self._fix_old_conf_file_settings(decoder(data))
            log.info('Loaded settings file: %s', path)
            self.conf_file_settings.update(decoded)
            self._assert_valid_settings()
            self._combine_settings()
        except (IOError, OSError) as err:
            log.info('%s: Failed to update settings from %s', err, path)

    @staticmethod
    def _fix_old_conf_file_settings(settings_dict):
        if 'API_INTERFACE' in settings_dict:
            settings_dict['api_host'] = settings_dict['API_INTERFACE']
            del settings_dict['API_INTERFACE']
        if 'startup_scripts' in settings_dict:
            del settings_dict['startup_scripts']
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

    def get_lbry_id(self):
        lbry_id_filename = os.path.join(self.ensure_data_dir(), 'lbryid')
        if not self._lbry_id:
            if os.path.isfile(lbry_id_filename):
                with open(lbry_id_filename, 'r') as lbryid_file:
                    self._lbry_id = base58.b58decode(lbryid_file.read())
        if not self._lbry_id:
            self._lbry_id = utils.generate_id()
            with open(lbry_id_filename, 'w') as lbryid_file:
                lbryid_file.write(base58.b58encode(self._lbry_id))
        return self._lbry_id

    def get_session_id(self):
        return self._session_id


# type: Config
settings = None


def initialize_settings(load_conf_file=True):
    global settings
    if settings is None:
        settings = Config(FIXED_SETTINGS, ADJUSTABLE_SETTINGS)
        if load_conf_file:
            settings.load_conf_file_settings()
