import copy
import json
import logging
import os
import sys
import yaml

from appdirs import user_data_dir
import envparse

LBRYCRD_WALLET = 'lbrycrd'
LBRYUM_WALLET = 'lbryum'
PTC_WALLET = 'ptc'

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


class Settings(object):
    """A collection of configuration settings"""
    __fixed = []
    _excluded = ['get_dict', 'update']

    def __iter__(self):
        for k in self.__dict__.iterkeys():
            if k.startswith('_') or k in self._excluded:
                continue
            yield k

    def __getitem__(self, item):
        assert item in self, IndexError
        return self.__dict__[item]

    def __setitem__(self, key, value):
        assert key in self and key not in self.__fixed, KeyError(key)
        self.__dict__[key] = value

    def __contains__(self, item):
        return item in iter(self)

    def get_dict(self):
        return {k: self[k] for k in self}

    def update(self, updated_settings):
        for k, v in updated_settings.iteritems():
            try:
                self.__setitem__(k, v)
            except (KeyError, AssertionError):
                pass


class Env(envparse.Env):
    """An Env parser that automatically namespaces the variables with LBRY"""
    NAMESPACE = 'LBRY_'
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

    def _convert_key(self, key):
        return Env.NAMESPACE + key.upper()

    def _convert_value(self, value):
        """Allow value to be specified as an object, tuple or dict

        if object or dict, follow default envparse rules, if tuple
        it needs to be of the form (cast, default) or (cast, default, subcast)
        """
        if isinstance(value, dict):
            return value
        if isinstance(value, (tuple, list)):
            new_value = {'cast': value[0], 'default': value[1]}
            if len(value) == 3:
                new_value['subcast'] = value[2]
            return new_value
        return value


def server_port(server_port):
    server, port = server_port.split(':')
    return server, int(port)


DEFAULT_DHT_NODES = [
    ('lbrynet1.lbry.io', 4444),
    ('lbrynet2.lbry.io', 4444),
    ('lbrynet3.lbry.io', 4444)
]


ENVIRONMENT = Env(
    is_generous_host=(bool, True),
    run_on_startup=(bool, False),
    download_directory=(str, default_download_directory),
    max_upload=(float, 0.0),
    max_download=(float, 0.0),
    upload_log=(bool, True),
    delete_blobs_on_remove=(bool, True),
    use_upnp=(bool, True),
    start_lbrycrdd=(bool, True),
    run_reflector_server=(bool, False),
    startup_scripts=(list, []),
    # TODO: this doesn't seem like the kind of thing that should
    # be configured; move it elsewhere.
    last_version=(dict, {'lbrynet': '0.0.1', 'lbryum': '0.0.1'}),
    peer_port=(int, 3333),
    dht_node_port=(int, 4444),
    reflector_port=(int, 5566),
    download_timeout=(int, 30),
    max_search_results=(int, 25),
    cache_time=(int, 150),
    search_timeout=(float, 5.0),
    host_ui=(bool, True),
    check_ui_requirements=(bool, True),
    local_ui_path=(bool, False),
    api_port=(int, 5279),
    search_servers=(list, ['lighthouse1.lbry.io:50005']),
    data_rate=(float, .0001),  # points/megabyte
    min_info_rate=(float, .02),  # points/1000 infos
    min_valuable_info_rate=(float, .05),  # points/1000 infos
    min_valuable_hash_rate=(float, .05),  # points/1000 infos
    max_connections_per_stream=(int, 5),
    known_dht_nodes=(list, DEFAULT_DHT_NODES, server_port),
    pointtrader_server=(str, 'http://127.0.0.1:2424'),
    reflector_servers=(list, [("reflector.lbry.io", 5566)], server_port),
    wallet=(str, LBRYUM_WALLET),
    ui_branch=(str, "master"),
    default_ui_branch=(str, 'master'),
    data_dir=(str, default_data_dir),
    lbryum_wallet_dir=(str, default_lbryum_dir),
    use_auth_http=(bool, False),
    sd_download_timeout=(int, 3),
    # TODO: this field is more complicated than it needs to be because
    # it goes through a Fee validator when loaded by the exchange rate
    # manager.  Look into refactoring the exchange rate conversion to
    # take in a simpler form.
    #
    # TODO: writing json on the cmd line is a pain, come up with a nicer
    # parser for this data structure. (maybe MAX_KEY_FEE=USD:25
    max_key_fee=(json.loads, {'USD': {'amount': 25.0, 'address': ''}}),
    # Changing this value is not-advised as it could potentially
    # expose the lbrynet daemon to the outside world which would
    # give an attacker access to your wallet and you could lose
    # all of your credits.
    API_INTERFACE=(str, "localhost"),
)


class AdjustableSettings(Settings):
    _excluded = ['get_dict', 'update', 'environ']

    """Settings that are allowed to be overriden by the user"""
    def __init__(self, environ=None):
        self.environ = environ or ENVIRONMENT

        for opt in self.environ.original_schema:
            self.__dict__[opt] = self.environ(opt)

        Settings.__init__(self)

    def __getattr__(self, attr):
        if attr in self.environ.original_schema:
            return self.environ(attr)
        raise AttributeError

class ApplicationSettings(Settings):
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
        self.API_ADDRESS = "lbryapi"
        self.ICON_PATH = "icons" if platform is WINDOWS else "app.icns"
        self.APP_NAME = "LBRY"
        self.PROTOCOL_PREFIX = "lbry"
        self.WALLET_TYPES = [LBRYUM_WALLET, LBRYCRD_WALLET]
        self.SOURCE_TYPES = ['lbry_sd_hash', 'url', 'btih']
        self.CURRENCIES = {
            'BTC': {'type': 'crypto'},
            'LBC': {'type': 'crypto'},
            'USD': {'type': 'fiat'},
        }
        self.LOGGLY_TOKEN = 'LJEzATH4AzRgAwxjAP00LwZ2YGx3MwVgZTMuBQZ3MQuxLmOv'
        self.ANALYTICS_ENDPOINT = 'https://api.segment.io/v1'
        self.ANALYTICS_TOKEN = 'Ax5LZzR1o3q3Z3WjATASDwR5rKyHH0qOIRIbLmMXn2H='
        self.DB_REVISION_FILE_NAME = 'db_revision' 
        Settings.__init__(self)


APPLICATION_SETTINGS = AdjustableSettings()
ADJUSTABLE_SETTINGS = AdjustableSettings()


class DefaultSettings(ApplicationSettings, AdjustableSettings):
    __fixed = APPLICATION_SETTINGS.get_dict().keys()

    def __init__(self):
        ApplicationSettings.__init__(self)
        AdjustableSettings.__init__(self)

    def get_dict(self):
        d = ApplicationSettings.get_dict(self)
        d.update(AdjustableSettings.get_dict(self))
        return d


DEFAULT_SETTINGS = DefaultSettings()


class Config(DefaultSettings):
    __shared_state = copy.deepcopy(DEFAULT_SETTINGS.get_dict())

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

    def get_dict(self):
        return {k: self[k] for k in self}

    def get_adjustable_settings_dict(self):
        return {opt: val for opt, val in self.get_dict().iteritems() if opt in self.environ.original_schema}

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

    def get_db_revision_filename(self):
        return os.path.join(self.ensure_data_dir(), self.DB_REVISION_FILE_NAME) 

    def get_conf_filename(self):
        return get_settings_file_ext(self.ensure_data_dir())


def update_settings_from_file(filename=None):
    filename = filename or settings.get_conf_filename()
    try:
        updates = load_settings(filename)
        log.info("Loaded settings file: %s", updates)
        settings.update(updates)
    except (IOError, OSError) as ex:
        log.info('%s: Failed to update settings from %s', ex, filename)


def get_settings_file_ext(data_dir):
    yml_path = os.path.join(data_dir, "daemon_settings.yml")
    json_path = os.path.join(data_dir, "daemon_settings.json")
    if os.path.isfile(yml_path):
        return yml_path
    elif os.path.isfile(json_path):
        return json_path
    else:
        return yml_path


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
    to_save = settings.get_adjustable_settings_dict()

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
