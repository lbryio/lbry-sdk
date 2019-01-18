import logging
from lbrynet.custom_logger import install_logger


__name__ = "lbrynet"
__version__ = "0.30.5"
version = tuple(__version__.split('.'))

install_logger()
logging.getLogger(__name__).addHandler(logging.NullHandler())
