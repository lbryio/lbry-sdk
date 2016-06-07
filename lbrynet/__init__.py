import logging

log = logging.getLogger(__name__)
logging.getLogger(__name__).addHandler(logging.NullHandler())
log.setLevel(logging.ERROR)

version = (0, 2, 5)
__version__ = ".".join([str(x) for x in version])
