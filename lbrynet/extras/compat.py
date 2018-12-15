import asyncio
from twisted.internet import defer


def d2f(deferred):
    return deferred.asFuture(asyncio.get_event_loop())


def f2d(future):
    return defer.Deferred.fromFuture(asyncio.ensure_future(future))
