import logging
import logging.handlers
import sys


DEFAULT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s:%(lineno)d: %(message)s"
DEFAULT_FORMATTER = logging.Formatter(DEFAULT_FORMAT)


def configureConsole(log=None, level=logging.INFO):
    """Convenience function to configure a logger that outputs to stdout"""
    log = log or logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(DEFAULT_FORMATTER)
    log.addHandler(handler)
    log.setLevel(level=level)


def configureFileHandler(file_name, log=None, level=logging.INFO):
    log = log or logging.getLogger()
    handler = logging.handlers.RotatingFileHandler(file_name, maxBytes=2097152, backupCount=5)
    handler.setFormatter(DEFAULT_FORMATTER)
    log.addHandler(handler)
    log.setLevel(level=level)
