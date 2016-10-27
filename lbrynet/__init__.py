import logging
from conf import Config

__version__ = "0.6.9"
version = tuple(__version__.split('.'))

# TODO: don't load the configuration automatically. The configuration
#       should be loaded at runtime, not at module import time. Module
#       import should have no side-effects. This is also bad because
#       it means that settings are read from the environment even for
#       tests, which is rarely what you want to happen.
settings = Config()
logging.getLogger(__name__).addHandler(logging.NullHandler())
