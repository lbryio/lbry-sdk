import datetime
import inspect
import json
import logging
import logging.handlers
import os
import platform
import sys
import traceback

import requests
from requests_futures.sessions import FuturesSession
import twisted.python.log

import lbrynet
from lbrynet import analytics
from lbrynet import build_type
from lbrynet import conf
from lbrynet.core import utils

####
# This code is copied from logging/__init__.py in the python source code
####
#
# _srcfile is used when walking the stack to check when we've got the first
# caller stack frame.
#
if hasattr(sys, 'frozen'): #support for py2exe
    _srcfile = "logging%s__init__%s" % (os.sep, __file__[-4:])
elif __file__[-4:].lower() in ['.pyc', '.pyo']:
    _srcfile = __file__[:-4] + '.py'
else:
    _srcfile = __file__
_srcfile = os.path.normcase(_srcfile)
#####


session = FuturesSession()
TRACE = 5


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
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('BitcoinRPC').setLevel(logging.INFO)
    logging.getLogger('lbryum').setLevel(logging.WARNING)
    logging.getLogger('twisted').setLevel(logging.WARNING)


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


def configure_analytics_handler(analytics_manager):
    handler = analytics.Handler(analytics_manager)
    handler.name = 'analytics'
    return configure_handler(handler, logging.getLogger(), logging.ERROR)


def get_loggly_url(token=None, version=None):
    token = token or utils.deobfuscate(conf.settings['LOGGLY_TOKEN'])
    version = version or lbrynet.__version__
    return LOGGLY_URL.format(token=token, tag='lbrynet-' + version)


def configure_loggly_handler(*args, **kwargs):
    if build_type.BUILD == 'dev':
        return
    _configure_loggly_handler(*args, **kwargs)


@_log_decorator
def _configure_loggly_handler(url=None, **kwargs):
    url = url or get_loggly_url()
    formatter = JsonFormatter(**kwargs)
    handler = HTTPSHandler(url)
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

####
# This code is copied from logging/__init__.py in the python source code
####
def findCaller(srcfile=None):
    """Returns the filename, line number and function name of the caller"""
    srcfile = srcfile or _srcfile
    f = inspect.currentframe()
    #On some versions of IronPython, currentframe() returns None if
    #IronPython isn't run with -X:Frames.
    if f is not None:
        f = f.f_back
    rv = "(unknown file)", 0, "(unknown function)"
    while hasattr(f, "f_code"):
        co = f.f_code
        filename = os.path.normcase(co.co_filename)
        # ignore any function calls that are in this file
        if filename == srcfile:
            f = f.f_back
            continue
        rv = (filename, f.f_lineno, co.co_name)
        break
    return rv
###


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
    configure_loggly_handler()
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


class LoggerNameFilter(object):
    """Filter a log record based on its name.

    Allows all info level and higher records to pass thru.
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


class LogUploader(object):
    def __init__(self, log_name, log_file, log_size):
        self.log_name = log_name
        self.log_file = log_file
        self.log_size = log_size

    def upload(self, exclude_previous, id_hash, log_type):
        if not os.path.isfile(self.log_file):
            return
        log_contents = self.log_contents(exclude_previous)
        params = {
            'date': datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S'),
            'hash': id_hash,
            'sys': platform.system(),
            'type': self.get_type(log_type),
            'log': log_contents
        }
        requests.post(conf.settings['LOG_POST_URL'], params)

    def log_contents(self, exclude_previous):
        with open(self.log_file) as f:
            if exclude_previous:
                f.seek(self.log_size)
                log_contents = f.read()
            else:
                log_contents = f.read()
        return log_contents

    def get_type(self, log_type):
        if log_type:
            return "%s-%s" % (self.log_name, log_type)
        else:
            return self.log_name

    @classmethod
    def load(cls, log_name, log_file):
        if os.path.isfile(log_file):
            with open(log_file, 'r') as f:
                log_size = len(f.read())
        else:
            log_size = 0
        return cls(log_name, log_file, log_size)


class Logger(logging.Logger):
    """A logger that has an extra `fail` method useful for handling twisted failures."""
    def fail(self, callback=None, *args, **kwargs):
        """Returns a function to log a failure from an errback.

        The returned function appends the error message and extracts
        the traceback from `err`.

        Example usage:
            d.addErrback(log.fail(), 'This is an error message')

        Although odd, making the method call is necessary to extract
        out useful filename and line number information; otherwise the
        reported values are from inside twisted's deferred handling
        code.

        Args:
            callback: callable to call after making the log. The first argument
                will be the `err` from the deferred
            args: extra arguments to pass into `callback`

        Returns: a function that takes the following arguments:
            err: twisted.python.failure.Failure
            msg: the message to log, using normal logging string iterpolation.
            msg_args: the values to subtitute into `msg`
            msg_kwargs: set `level` to change from the default ERROR severity. Other
                keywoards are treated as normal log kwargs.
        """
        fn, lno, func = findCaller()
        def _fail(err, msg, *msg_args, **msg_kwargs):
            level = msg_kwargs.pop('level', logging.ERROR)
            msg += ": %s"
            msg_args += (err.getErrorMessage(),)
            exc_info = (err.type, err.value, err.getTracebackObject())
            record = self.makeRecord(
                self.name, level, fn, lno, msg, msg_args, exc_info, func, msg_kwargs)
            self.handle(record)
            if callback:
                try:
                    return callback(err, *args, **kwargs)
                except Exception:
                    # log.fail is almost always called within an
                    # errback. If callback fails and we didn't catch
                    # the exception we would need to attach a second
                    # errback to deal with that, which we will almost
                    # never do and then we end up with an unhandled
                    # error that will get swallowed by twisted
                    self.exception('Failed to run callback')
        return _fail

    def trace(self, msg, *args, **kwargs):
        if self.isEnabledFor(TRACE):
            self._log(TRACE, msg, args, **kwargs)


logging.setLoggerClass(Logger)
logging.addLevelName(TRACE, 'TRACE')
