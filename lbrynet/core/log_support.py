import json
import logging
import logging.handlers
import sys
import traceback

from requests_futures.sessions import FuturesSession

import lbrynet
from lbrynet import conf
from lbrynet.core import utils

session = FuturesSession()


def bg_cb(sess, resp):
    """ Don't do anything with the response """
    pass


class HTTPSHandler(logging.Handler):
    def __init__(self, url, fqdn=False, localname=None, facility=None):
        logging.Handler.__init__(self)
        self.url = url
        self.fqdn = fqdn
        self.localname = localname
        self.facility = facility

    def get_full_message(self, record):
        if record.exc_info:
            return '\n'.join(traceback.format_exception(*record.exc_info))
        else:
            return record.getMessage()

    def emit(self, record):
        try:
            payload = self.format(record)
            session.post(self.url, data=payload, background_callback=bg_cb)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


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
        if not isinstance(level, int):
            # despite the name, getLevelName returns
            # the numeric level when passed a text level
            level = logging.getLevelName(level)
        handler = fn(*args, **kwargs)
        if handler.name:
            remove_handlers(log, handler.name)
        handler.setLevel(level)
        log.addHandler(handler)
        if log.level > level:
            log.setLevel(level)
    return helper


def disable_third_party_loggers():
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('BitcoinRPC').setLevel(logging.INFO)

def disable_noisy_loggers():
    logging.getLogger('lbrynet.analytics.api').setLevel(logging.INFO)
    logging.getLogger('lbrynet.core').setLevel(logging.INFO)
    logging.getLogger('lbrynet.dht').setLevel(logging.INFO)
    logging.getLogger('lbrynet.lbrynet_daemon').setLevel(logging.INFO)
    logging.getLogger('lbrynet.core.Wallet').setLevel(logging.INFO)
    logging.getLogger('lbrynet.lbryfile').setLevel(logging.INFO)
    logging.getLogger('lbrynet.lbryfilemanager').setLevel(logging.INFO)


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
    token = token or utils.deobfuscate(conf.LOGGLY_TOKEN)
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
    handler = HTTPSHandler(url)
    handler.setFormatter(formatter)
    handler.name = 'loggly'
    return handler
