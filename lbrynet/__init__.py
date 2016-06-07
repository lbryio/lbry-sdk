import logging
import logging.handlers
import sys
import os
from lbrynet.conf import LOG_FILE_NAME
from appdirs import user_data_dir

if sys.platform != "darwin":
    log_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    log_dir = user_data_dir("LBRY")

if not os.path.isdir(log_dir):
    os.mkdir(log_dir)

LOG_PATH = os.path.join(log_dir, LOG_FILE_NAME)

if os.path.isfile(LOG_PATH):
    f = open(LOG_PATH, 'r')
    PREVIOUS_LOG = len(f.read())
    f.close()
else:
    PREVIOUS_LOG = 0

log = logging.getLogger(__name__)
log.addHandler(logging.FileHandler(filename=LOG_PATH))
log.setLevel(logging.ERROR)

version = (0, 2, 5)
__version__ = ".".join([str(x) for x in version])
