import logging

__version__ = "0.4.7"
version = tuple(__version__.split('.'))

logging.getLogger(__name__).addHandler(logging.NullHandler())