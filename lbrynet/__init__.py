import logging

__version__ = "0.16.0rc8"
version = tuple(__version__.split('.'))

logging.getLogger(__name__).addHandler(logging.NullHandler())
