"""
Some network wide and also application specific parameters
"""
import os


IS_DEVELOPMENT_VERSION = True

MAX_HANDSHAKE_SIZE = 2**16
MAX_REQUEST_SIZE = 2**16
MAX_BLOB_REQUEST_SIZE = 2**16
MAX_RESPONSE_INFO_SIZE = 2**16
MAX_BLOB_INFOS_TO_REQUEST = 20
BLOBFILES_DIR = ".blobfiles"
BLOB_SIZE = 2**21

MIN_BLOB_DATA_PAYMENT_RATE = .005  # points/megabyte
MIN_BLOB_INFO_PAYMENT_RATE = .02  # points/1000 infos
MIN_VALUABLE_BLOB_INFO_PAYMENT_RATE = .05  # points/1000 infos
MIN_VALUABLE_BLOB_HASH_PAYMENT_RATE = .05  # points/1000 infos
MAX_CONNECTIONS_PER_STREAM = 5

KNOWN_DHT_NODES = [('104.236.42.182', 4000),
                   ('lbrynet1.lbry.io', 4444),
                   ('lbrynet2.lbry.io', 4444),
                   ('lbrynet3.lbry.io', 4444)]

POINTTRADER_SERVER = 'http://ec2-54-187-192-68.us-west-2.compute.amazonaws.com:2424'
#POINTTRADER_SERVER = 'http://127.0.0.1:2424'

if IS_DEVELOPMENT_VERSION:
    SEARCH_SERVERS = ["http://107.170.207.64:50005"]
else:
    SEARCH_SERVERS = ["http://lighthouse1.lbry.io:50005",
                      "http://lighthouse2.lbry.io:50005",
                      "http://lighthouse3.lbry.io:50005"]

REFLECTOR_SERVERS = [("reflector.lbry.io", 5566)]

LOG_FILE_NAME = "lbrynet.log"
LOG_POST_URL = "https://lbry.io/log-upload"

CRYPTSD_FILE_EXTENSION = ".cryptsd"

API_INTERFACE = "localhost"
API_ADDRESS = "lbryapi"
API_PORT = 5279
if os.name == "nt":
    ICON_PATH = "icons"
else:
    ICON_PATH = "app.icns"
APP_NAME = "LBRY"
API_CONNECTION_STRING = "http://%s:%i/%s" % (API_INTERFACE, API_PORT, API_ADDRESS)
UI_ADDRESS = "http://%s:%i" % (API_INTERFACE, API_PORT)
PROTOCOL_PREFIX = "lbry"

DEFAULT_WALLET = "lbryum"
WALLET_TYPES = ["lbryum", "lbrycrd"]
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_SEARCH_RESULTS = 25
DEFAULT_MAX_KEY_FEE = {'USD': {'amount': 25.0, 'address': ''}}
DEFAULT_SEARCH_TIMEOUT = 3.0
DEFAULT_SD_DOWNLOAD_TIMEOUT = 3
DEFAULT_CACHE_TIME = 3600
DEFAULT_UI_BRANCH = "master"

SOURCE_TYPES = ['lbry_sd_hash', 'url', 'btih']
CURRENCIES = {
                'BTC': {'type': 'crypto'},
                'LBC': {'type': 'crypto'},
                'USD': {'type': 'fiat'},
             }

LOGGLY_TOKEN = 'LJEzATH4AzRgAwxjAP00LwZ2YGx3MwVgZTMuBQZ3MQuxLmOv'

ANALYTICS_ENDPOINT = 'https://api.segment.io/v1'
ANALYTICS_TOKEN = 'Ax5LZzR1o3q3Z3WjATASDwR5rKyHH0qOIRIbLmMXn2H='
