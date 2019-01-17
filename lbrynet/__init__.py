import logging


__name__ = "lbrynet"
__version__ = "0.31.1rc1"
version = tuple(__version__.split('.'))

logging.getLogger(__name__).addHandler(logging.NullHandler())
