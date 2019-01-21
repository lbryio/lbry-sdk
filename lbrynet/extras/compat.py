import asyncio


def force_asyncioreactor_install():
    import sys
    from twisted.internet import asyncioreactor
    if 'twisted.internet.reactor' not in sys.modules:
        asyncioreactor.install()
    else:
        from twisted.internet import reactor
        if not isinstance(reactor, asyncioreactor.AsyncioSelectorReactor) and getattr(sys, 'frozen', False):
            # pyinstaller hooks install the default reactor before
            # any of our code runs, see kivy for similar problem:
            #    https://github.com/kivy/kivy/issues/4182
            del sys.modules['twisted.internet.reactor']
            asyncioreactor.install()


def d2f(deferred):
    return deferred.asFuture(asyncio.get_event_loop())


def f2d(future):
    from twisted.internet import defer
    return defer.Deferred.fromFuture(asyncio.ensure_future(future))
