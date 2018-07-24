import logging
import customLogger

__version__ = "0.20.4"
version = tuple(__version__.split('.'))

logging.getLogger(__name__).addHandler(logging.NullHandler())
