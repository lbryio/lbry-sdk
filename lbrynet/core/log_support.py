import base64
import json
import logging
import logging.handlers
import sys

import loggly.handlers

import lbrynet
from lbrynet import conf


DEFAULT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s:%(lineno)d: %(message)s"
DEFAULT_FORMATTER = logging.Formatter(DEFAULT_FORMAT)
LOGGLY_URL = "https://logs-01.loggly.com/inputs/{token}/tag/{tag}"


def remove_handlers(log, handler_name):
    for handler in log.handlers:
        if handler.name == handler_name:
            log.removeHandler(handler)


def _log_decorator(fn):
    def helper(*args, **kwargs):
        log = kwargs.pop('log', logging.getLogger())
        level = kwargs.pop('level', logging.INFO)
        handler = fn(*args, **kwargs)
        if handler.name:
            remove_handlers(log, handler.name)
        log.addHandler(handler)
        log.setLevel(level)
    return helper


def disable_noisy_loggers():
    logging.getLogger('requests').setLevel(logging.WARNING)


@_log_decorator
def configure_console(**kwargs):
    """Convenience function to configure a logger that outputs to stdout"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(DEFAULT_FORMATTER)
    handler.name = 'console'
    return handler


@_log_decorator
def configure_file_handler(file_name, **kwargs):
    handler = logging.handlers.RotatingFileHandler(file_name, maxBytes=2097152, backupCount=5)
    handler.setFormatter(DEFAULT_FORMATTER)
    handler.name = 'file'
    return handler


def get_loggly_url(token=None, version=None):
    token = token or base64.b64decode(conf.LOGGLY_TOKEN)
    version = version or lbrynet.__version__
    return LOGGLY_URL.format(token=token, tag='lbrynet-' + version)


@_log_decorator
def configure_loggly_handler(url=None, **kwargs):
    url = url or get_loggly_url()
    json_format = {
        "loggerName": "%(name)s",
        "asciTime": "%(asctime)s",
        "fileName": "%(filename)s",
        "functionName": "%(funcName)s",
        "levelNo": "%(levelno)s",
        "lineNo": "%(lineno)d",
        "levelName": "%(levelname)s",
        "message": "%(message)s",
    }
    json_format.update(kwargs)
    formatter = logging.Formatter(json.dumps(json_format))
    handler = loggly.handlers.HTTPSHandler(url)
    handler.setFormatter(formatter)
    handler.name = 'loggly'
    return handler
