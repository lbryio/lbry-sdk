from zope.interface import implements
from lbrynet.interfaces import IRateLimiter
from twisted.internet import task


class DummyRateLimiter(object):
    def __init__(self):
        self.dl_bytes_this_second = 0
        self.ul_bytes_this_second = 0
        self.total_dl_bytes = 0
        self.total_ul_bytes = 0
        self.target_dl = 0
        self.target_ul = 0
        self.tick_call = None

    def start(self):
        self.tick_call = task.LoopingCall(self.tick)
        self.tick_call.start(1)

    def tick(self):
        self.dl_bytes_this_second = 0
        self.ul_bytes_this_second = 0

    def stop(self):
        if self.tick_call is not None:
            self.tick_call.stop()
            self.tick_call = None

    def set_dl_limit(self, limit):
        pass

    def set_ul_limit(self, limit):
        pass

    def report_dl_bytes(self, num_bytes):
        self.dl_bytes_this_second += num_bytes
        self.total_dl_bytes += num_bytes

    def report_ul_bytes(self, num_bytes):
        self.ul_bytes_this_second += num_bytes
        self.total_ul_bytes += num_bytes


class RateLimiter(object):
    """This class ensures that upload and download rates don't exceed specified maximums"""

    implements(IRateLimiter)

    #called by main application

    def __init__(self, max_dl_bytes=None, max_ul_bytes=None):
        self.max_dl_bytes = max_dl_bytes
        self.max_ul_bytes = max_ul_bytes
        self.dl_bytes_this_interval = 0
        self.ul_bytes_this_interval = 0
        self.total_dl_bytes = 0
        self.total_ul_bytes = 0
        self.tick_call = None
        self.tick_interval = 0.1

        self.dl_throttled = False
        self.ul_throttled = False

        self.protocols = []

    def start(self):
        self.tick_call = task.LoopingCall(self.tick)
        self.tick_call.start(self.tick_interval)

    def tick(self):
        self.dl_bytes_this_interval = 0
        self.ul_bytes_this_interval = 0
        self.unthrottle_dl()
        self.unthrottle_ul()

    def stop(self):
        if self.tick_call is not None:
            self.tick_call.stop()
            self.tick_call = None

    def set_dl_limit(self, limit):
        self.max_dl_bytes = limit

    def set_ul_limit(self, limit):
        self.max_ul_bytes = limit

    #throttling

    def check_dl(self):

        if self.max_dl_bytes is not None and self.dl_bytes_this_interval > self.max_dl_bytes * self.tick_interval:
            from twisted.internet import reactor
            reactor.callLater(0, self.throttle_dl)

    def check_ul(self):

        if self.max_ul_bytes is not None and self.ul_bytes_this_interval > self.max_ul_bytes * self.tick_interval:
            from twisted.internet import reactor
            reactor.callLater(0, self.throttle_ul)

    def throttle_dl(self):
        if self.dl_throttled is False:
            for protocol in self.protocols:
                protocol.throttle_download()
            self.dl_throttled = True

    def throttle_ul(self):
        if self.ul_throttled is False:
            for protocol in self.protocols:
                protocol.throttle_upload()
            self.ul_throttled = True

    def unthrottle_dl(self):
        if self.dl_throttled is True:
            for protocol in self.protocols:
                protocol.unthrottle_download()
            self.dl_throttled = False

    def unthrottle_ul(self):
        if self.ul_throttled is True:
            for protocol in self.protocols:
                protocol.unthrottle_upload()
            self.ul_throttled = False

    #called by protocols

    def report_dl_bytes(self, num_bytes):
        self.dl_bytes_this_interval += num_bytes
        self.total_dl_bytes += num_bytes
        self.check_dl()

    def report_ul_bytes(self, num_bytes):
        self.ul_bytes_this_interval += num_bytes
        self.total_ul_bytes += num_bytes
        self.check_ul()

    def register_protocol(self, protocol):
        if protocol not in self.protocols:
            self.protocols.append(protocol)
            if self.dl_throttled is True:
                protocol.throttle_download()
            if self.ul_throttled is True:
                protocol.throttle_upload()

    def unregister_protocol(self, protocol):
        if protocol in self.protocols:
            self.protocols.remove(protocol)