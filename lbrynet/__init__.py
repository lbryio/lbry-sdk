import logging

__name__ = "lbrynet"
__version__ = "0.30.0rc6"
version = tuple(__version__.split('.'))

logging.getLogger(__name__).addHandler(logging.NullHandler())
