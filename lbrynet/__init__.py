import logging


logging.getLogger(__name__).addHandler(logging.NullHandler())


version = (0, 2, 4)
__version__ = ".".join([str(x) for x in version])
