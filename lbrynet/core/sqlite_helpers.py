import sqlite3
from twisted.internet import task, reactor
import logging


log = logging.getLogger(__name__)


def rerun_if_locked(f):

    def rerun(err, *args, **kwargs):
        if err.check(sqlite3.OperationalError) and err.value.message == "database is locked":
            log.warning("database was locked. rerunning %s with args %s, kwargs %s",
                        str(f), str(args), str(kwargs))
            return task.deferLater(reactor, 0, wrapper, *args, **kwargs)
        return err

    def wrapper(*args, **kwargs):
        d = f(*args, **kwargs)
        d.addErrback(rerun, *args, **kwargs)
        return d

    return wrapper