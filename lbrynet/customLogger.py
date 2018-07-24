import os
import sys
import inspect
import logging
TRACE = 5


####
# This code is copied from logging/__init__.py in the python source code
####
#
# _srcfile is used when walking the stack to check when we've got the first
# caller stack frame.
#
if hasattr(sys, 'frozen'):  # support for py2exe
    _srcfile = "logging%s__init__%s" % (os.sep, __file__[-4:])
elif __file__[-4:].lower() in ['.pyc', '.pyo']:
    _srcfile = __file__[:-4] + '.py'
else:
    _srcfile = __file__
_srcfile = os.path.normcase(_srcfile)


def findCaller(srcfile=None):
    """Returns the filename, line number and function name of the caller"""
    srcfile = srcfile or _srcfile
    f = inspect.currentframe()
    # On some versions of IronPython, currentframe() returns None if
    # IronPython isn't run with -X:Frames.
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
