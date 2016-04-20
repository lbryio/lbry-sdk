import logging


logging.getLogger(__name__).addHandler(logging.NullHandler())


version = (0, 2, 3)
__version__ = ".".join([str(x) for x in version])
