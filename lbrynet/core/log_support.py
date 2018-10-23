import json
import logging
import logging.handlers
import sys
import traceback

import treq
from twisted.internet import defer
import twisted.python.log

from lbrynet import __version__ as lbrynet_version, build_type, conf
from lbrynet.core import utils


class HTTPSHandler(logging.Handler):
    def __init__(self, url, fqdn=False, localname=None, facility=None, cookies=None):
        super().__init__()
        self.url = url
        self.fqdn = fqdn
        self.localname = localname
        self.facility = facility
        self.cookies = cookies or {}

    def get_full_message(self, record):
        if record.exc_info:
            return '\n'.join(traceback.format_exception(*record.exc_info))
        else:
            return record.getMessage()

    @defer.inlineCallbacks
    def _emit(self, record):
        payload = self.format(record)
        response = yield treq.post(self.url, data=payload, cookies=self.cookies)
        self.cookies.update(response.cookies())

    def emit(self, record):
        return self._emit(record)


DEFAULT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s:%(lineno)d: %(message)s"
DEFAULT_FORMATTER = logging.Formatter(DEFAULT_FORMAT)
LOGGLY_URL = "https://logs-01.loggly.com/inputs/{token}/tag/{tag}"


def remove_handlers(log, handler_name):
    for handler in log.handlers:
        if handler.name == handler_name:
            log.removeHandler(handler)


def _log_decorator(fn):
    """Configure a logging handler.

    `fn` is a function that returns a logging handler. The returned
    handler has its log-level set and is attached to the specified
    logger or the root logger.
    """

    def helper(*args, **kwargs):
        log = kwargs.pop('log', logging.getLogger())
        level = kwargs.pop('level', logging.INFO)
        if not isinstance(level, int):
            # despite the name, getLevelName returns
            # the numeric level when passed a text level
            level = logging.getLevelName(level)
        handler = fn(*args, **kwargs)
        configure_handler(handler, log, level)
        return handler

    return helper


def configure_handler(handler, log, level):
    if handler.name:
        remove_handlers(log, handler.name)
    handler.setLevel(level)
    log.addHandler(handler)
    # need to reduce the logger's level down to the
    # handler's level or else the handler won't
    # get those messages
    if log.level > level:
        log.setLevel(level)
    return handler


def disable_third_party_loggers():
    logging.getLogger('requests').setLevel(logging.CRITICAL)
    logging.getLogger('urllib3').setLevel(logging.CRITICAL)
    logging.getLogger('BitcoinRPC').setLevel(logging.INFO)
    logging.getLogger('lbryum').setLevel(logging.WARNING)
    logging.getLogger('twisted').setLevel(logging.CRITICAL)
    logging.getLogger('aioupnp').setLevel(logging.WARNING)


@_log_decorator
def configure_console(**kwargs):
    """Convenience function to configure a log-handler that outputs to stdout"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(DEFAULT_FORMATTER)
    handler.name = 'console'
    return handler


@_log_decorator
def configure_file_handler(file_name, **kwargs):
    """Convenience function to configure a log-handler that writes to `file_name`"""
    handler = logging.handlers.RotatingFileHandler(file_name, maxBytes=2097152, backupCount=5)
    handler.setFormatter(DEFAULT_FORMATTER)
    handler.name = 'file'
    return handler


def get_loggly_url(token=None, version=None):
    token = token or utils.deobfuscate(conf.settings['LOGGLY_TOKEN'])
    version = version or lbrynet_version
    return LOGGLY_URL.format(token=token, tag='lbrynet-' + version)


def configure_loggly_handler():
    if build_type.BUILD == 'dev':
        return
    if not conf.settings['share_usage_data']:
        return
    level = logging.ERROR
    handler = get_loggly_handler(level=level, installation_id=conf.settings.installation_id,
                                 session_id=conf.settings.get_session_id())
    log = logging.getLogger("lbrynet")
    if handler.name:
        remove_handlers(log, handler.name)
    handler.setLevel(level)
    log.addHandler(handler)
    # need to reduce the logger's level down to the
    # handler's level or else the handler won't
    # get those messages
    if log.level > level:
        log.setLevel(level)


def get_loggly_handler(level, installation_id, session_id):
    formatter = JsonFormatter(level=level, installation_id=installation_id, session_id=session_id)
    handler = HTTPSHandler(get_loggly_url())
    handler.setFormatter(formatter)
    handler.name = 'loggly'
    return handler


class JsonFormatter(logging.Formatter):
    """Format log records using json serialization"""

    def __init__(self, **kwargs):
        self.attributes = kwargs

    def format(self, record):
        data = {
            'loggerName': record.name,
            'asciTime': self.formatTime(record),
            'fileName': record.filename,
            'functionName': record.funcName,
            'levelNo': record.levelno,
            'lineNo': record.lineno,
            'levelName': record.levelname,
            'message': record.getMessage(),
        }
        data.update(self.attributes)
        if record.exc_info:
            data['exc_info'] = self.formatException(record.exc_info)
        return json.dumps(data)


def failure(failure, log, msg, *args):
    """Log a failure message from a deferred.

    Args:
        failure: twisted.python.failure.Failure
        log: a python logger instance
        msg: the message to log. Can use normal logging string interpolation.
             the last argument will be set to the error message from the failure.
        args: values to substitute into `msg`
    """
    args += (failure.getErrorMessage(),)
    exc_info = (failure.type, failure.value, failure.getTracebackObject())
    log.error(msg, *args, exc_info=exc_info)


def convert_verbose(verbose):
    """Convert the results of the --verbose flag into a list of logger names

    if --verbose is not provided, args.verbose will be None and logging
    should be at the info level.
    if --verbose is provided, but not followed by any arguments, then
    args.verbose = [] and debug logging should be enabled for all of lbrynet
    along with info logging on lbryum.
    if --verbose is provided and followed by arguments, those arguments
    will be in a list
    """
    if verbose is None:
        return []
    if verbose == []:
        return ['lbrynet', 'lbryum']
    return verbose


def configure_logging(file_name, console, verbose=None):
    """Apply the default logging configuration.

    Enables two log-handlers at the INFO level: a file logger and a loggly logger.
    Optionally turns on a console logger that defaults to the INFO level, with
    specified loggers being set to the DEBUG level.

    Args:
        file_name: the file to which logs should be saved
        console: If true, enable a console logger
        verbose: a list of loggers to set to debug level.
            See `convert_verbose` for more details.
    """
    verbose = convert_verbose(verbose)
    configure_twisted()
    configure_file_handler(file_name)
    disable_third_party_loggers()
    if console:
        # if there are some loggers at the debug level, we need
        # to enable the console to allow debug. Otherwise, only
        # allow info.
        level = 'DEBUG' if verbose else 'INFO'
        handler = configure_console(level=level)
        if 'lbryum' in verbose:
            # TODO: this enables lbryum logging on the other handlers
            # too which isn't consistent with how verbose logging
            # happens with other loggers. Should change the configuration
            # so that its only logging at the INFO level for the console.
            logging.getLogger('lbryum').setLevel(logging.INFO)
            verbose.remove('lbryum')
        if verbose:
            handler.addFilter(LoggerNameFilter(verbose))


def configure_twisted():
    """Setup twisted logging to output events to the python stdlib logger"""
    # I tried using the new logging api
    # https://twistedmatrix.com/documents/current/core/howto/logger.html#compatibility-with-standard-library-logging
    # and it simply didn't work
    observer = twisted.python.log.PythonLoggingObserver()
    observer.start()


class LoggerNameFilter:
    """Filter a log record based on its name.

    Allows all info level and higher records to pass through.
    Debug records pass if the log record name (or a parent) match
    the input list of logger names.
    """

    def __init__(self, logger_names):
        self.logger_names = logger_names

    def filter(self, record):
        if record.levelno >= logging.INFO:
            return True
        name = record.name
        while name:
            if name in self.logger_names:
                return True
            name = get_parent(name)
        return False


def get_parent(logger_name):
    names = logger_name.split('.')
    if len(names) == 1:
        return ''
    names = names[:-1]
    return '.'.join(names)
