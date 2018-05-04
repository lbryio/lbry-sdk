import logging

__version__ = "0.20.0rc9-tox"
version = tuple(__version__.split('.'))

logging.getLogger(__name__).addHandler(logging.NullHandler())
