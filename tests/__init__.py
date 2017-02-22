# log_support setups the default Logger class
# and so we need to ensure that it is also
# setup for the tests
from lbrynet.core import log_support
import logging

log_format = "%(funcName)s(): %(message)s"

log = logging.getLogger("tests")
log.setLevel(logging.INFO)
if not log.handlers:
    log.addHandler(logging.StreamHandler())