import copy
import os
import sys
from appdirs import user_data_dir

PRIORITIZE_ENV = True
LINUX = 1
DARWIN = 2
WINDOWS = 3

if sys.platform.startswith("darwin"):
    platform = DARWIN
    default_download_directory = os.path.join(os.path.expanduser("~"), 'Downloads')
    default_data_dir = user_data_dir("LBRY")
    default_lbryum_dir = os.path.join(os.path.expanduser("~"), ".lbryum")
elif sys.platform.startswith("win"):
    platform = WINDOWS
    from lbrynet.winhelpers.knownpaths import get_path, FOLDERID, UserHandle
    default_download_directory = get_path(FOLDERID.Downloads, UserHandle.current)
    default_data_dir = os.path.join(get_path(FOLDERID.RoamingAppData, UserHandle.current), "lbrynet")
    default_lbryum_dir = os.path.join(get_path(FOLDERID.RoamingAppData, UserHandle.current), "lbryum")
else:
    platform = LINUX
    default_download_directory = os.path.join(os.path.expanduser("~"), 'Downloads')
    default_data_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
    default_lbryum_dir = os.path.join(os.path.expanduser("~"), ".lbryum")

ADJUSTABLE_SETTINGS = {
    'run_on_startup': False,
    'download_directory': default_download_directory,
    'max_upload': 0.0,
    'max_download': 0.0,
    'upload_log': True,
    'delete_blobs_on_remove': True,
    'use_upnp': True,
    'start_lbrycrdd': True,
    'run_reflector_server': False,
    'startup_scripts': [],
    'last_version': {},
    'peer_port': 3333,
    'dht_node_port': 4444,
    'reflector_port': 5566,
    'download_timeout': 30,
    'max_search_results': 25,
    'search_timeout': 3.0,
    'cache_time': 150,
    'host_ui': True,
    'check_ui_requirements': True,
    'local_ui_path': False,
    'API_PORT': 5279,
    'search_servers':['lighthouse1.lbry.io:50005'],
    'data_rate': .0001,  # points/megabyte
    'MIN_BLOB_INFO_PAYMENT_RATE': .02,  # points/1000 infos
    'MIN_VALUABLE_BLOB_INFO_PAYMENT_RATE': .05,  # points/1000 infos
    'MIN_VALUABLE_BLOB_HASH_PAYMENT_RATE': .05,  # points/1000 infos
    'max_connections_per_stream': 5,
    'known_dht_nodes': [('104.236.42.182', 4000),
                        ('lbrynet1.lbry.io', 4444),
                        ('lbrynet2.lbry.io', 4444),
                        ('lbrynet3.lbry.io', 4444)],
    'POINTTRADER_SERVER': 'http://127.0.0.1:2424',
    'REFLECTOR_SERVERS': [("reflector.lbry.io", 5566)],
    'WALLET': "lbryum",
    'UI_BRANCH': "master",
    'DEFAULT_UI_BRANCH': 'master',
    'DATA_DIR': default_data_dir,
    'LBRYUM_WALLET_DIR': default_lbryum_dir,
    'USE_AUTH_HTTP': False,
    'sd_download_timeout': 3,
    'max_key_fee': {'USD': {'amount': 25.0, 'address': ''}}
}


class ApplicationSettings(object):
    MAX_HANDSHAKE_SIZE = 2**16
    MAX_REQUEST_SIZE = 2**16
    MAX_BLOB_REQUEST_SIZE = 2**16
    MAX_RESPONSE_INFO_SIZE = 2**16
    MAX_BLOB_INFOS_TO_REQUEST = 20
    BLOBFILES_DIR = "blobfiles"
    BLOB_SIZE = 2**21
    LOG_FILE_NAME = "lbrynet.log"
    LOG_POST_URL = "https://lbry.io/log-upload"
    CRYPTSD_FILE_EXTENSION = ".cryptsd"
    API_INTERFACE = "localhost"
    API_ADDRESS = "lbryapi"
    ICON_PATH = "icons" if platform is WINDOWS else "app.icns"
    APP_NAME = "LBRY"
    PROTOCOL_PREFIX = "lbry"
    WALLET_TYPES = ["lbryum", "lbrycrd"]
    SOURCE_TYPES = ['lbry_sd_hash', 'url', 'btih']
    CURRENCIES = {
                        'BTC': {'type': 'crypto'},
                        'LBC': {'type': 'crypto'},
                        'USD': {'type': 'fiat'},
    }
    LOGGLY_TOKEN = 'LJEzATH4AzRgAwxjAP00LwZ2YGx3MwVgZTMuBQZ3MQuxLmOv'
    ANALYTICS_ENDPOINT = 'https://api.segment.io/v1'
    ANALYTICS_TOKEN = 'Ax5LZzR1o3q3Z3WjATASDwR5rKyHH0qOIRIbLmMXn2H='

    @staticmethod
    def get_dict():
        r = {k: v for k, v in ApplicationSettings.__dict__.iteritems() if not k.startswith('__')}
        if PRIORITIZE_ENV:
            r = add_env_settings(r)
        return r


def add_env_settings(settings_dict):
    with_env_settings = copy.deepcopy(settings_dict)
    for setting, setting_val in settings_dict.iteritems():
        env_val = os.environ.get(setting, None)
        if env_val != setting_val and env_val is not None:
            with_env_settings.update({setting: env_val})
    return with_env_settings


DEFAULT_CONFIG = ApplicationSettings.get_dict()
DEFAULT_CONFIG.update(add_env_settings(ADJUSTABLE_SETTINGS))


class Config(object):
    __shared_state = copy.deepcopy(DEFAULT_CONFIG)

    def __init__(self):
        self.__dict__ = self.__shared_state

    def update(self, settings):
        for k, v in settings.iteritems():
            if k in ADJUSTABLE_SETTINGS:
                self.__dict__.update({k: v})

    @property
    def configurable_settings(self):
        return {k: v for k, v in copy.deepcopy(self.__dict__).iteritems() if k in ADJUSTABLE_SETTINGS}

    @property
    def ORIGIN(self):
        return "http://%s:%i" % (ApplicationSettings.API_INTERFACE, self.API_PORT)

    @property
    def REFERER(self):
        return "http://%s:%i/" % (ApplicationSettings.API_INTERFACE, self.API_PORT)

    @property
    def API_CONNECTION_STRING(self):
        return "http://%s:%i/%s" % (ApplicationSettings.API_INTERFACE, self.API_PORT, ApplicationSettings.API_ADDRESS)

    @property
    def UI_ADDRESS(self):
        return "http://%s:%i" % (ApplicationSettings.API_INTERFACE, self.API_PORT)

    @property
    def LBRYUM_WALLET_DIR(self):
        env_dir = os.environ.get('LBRYUM_WALLET_DIR')
        if env_dir:
            return env_dir
        return self.__dict__.get('LBRYUM_WALLET_DIR')
