from zope.interface import implements
from lbrynet.interfaces import IRateLimiter


class DummyRateLimiter(object):
    def __init__(self):
        self.dl_bytes_this_second = 0
        self.ul_bytes_this_second = 0
        self.total_dl_bytes = 0
        self.total_ul_bytes = 0
        self.target_dl = 0
        self.target_ul = 0
        self.ul_delay = 0.00
        self.dl_delay = 0.00
        self.next_tick = None

    def tick(self):

        from twisted.internet import reactor

        self.dl_bytes_this_second = 0
        self.ul_bytes_this_second = 0
        self.next_tick = reactor.callLater(1.0, self.tick)

    def stop(self):
        if self.next_tick is not None:
            self.next_tick.cancel()
            self.next_tick = None

    def set_dl_limit(self, limit):
        pass

    def set_ul_limit(self, limit):
        pass

    def ul_wait_time(self):
        return self.ul_delay

    def dl_wait_time(self):
        return self.dl_delay

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
        self.dl_bytes_this_second = 0
        self.ul_bytes_this_second = 0
        self.total_dl_bytes = 0
        self.total_ul_bytes = 0
        self.next_tick = None
        self.next_unthrottle_dl = None
        self.next_unthrottle_ul = None

        self.next_dl_check = None
        self.next_ul_check = None

        self.dl_check_interval = 1.0
        self.ul_check_interval = 1.0

        self.dl_throttled = False
        self.ul_throttled = False

        self.protocols = []

    def tick(self):

        from twisted.internet import reactor

        # happens once per second
        if self.next_dl_check is not None:
            self.next_dl_check.cancel()
            self.next_dl_check = None
        if self.next_ul_check is not None:
            self.next_ul_check.cancel()
            self.next_ul_check = None
        if self.max_dl_bytes is not None:
            if self.dl_bytes_this_second == 0:
                self.dl_check_interval = 1.0
            else:
                self.dl_check_interval = min(1.0, self.dl_check_interval *
                                             self.max_dl_bytes / self.dl_bytes_this_second)
            self.next_dl_check = reactor.callLater(self.dl_check_interval, self.check_dl)
        if self.max_ul_bytes is not None:
            if self.ul_bytes_this_second == 0:
                self.ul_check_interval = 1.0
            else:
                self.ul_check_interval = min(1.0, self.ul_check_interval *
                                             self.max_ul_bytes / self.ul_bytes_this_second)
            self.next_ul_check = reactor.callLater(self.ul_check_interval, self.check_ul)
        self.dl_bytes_this_second = 0
        self.ul_bytes_this_second = 0
        self.unthrottle_dl()
        self.unthrottle_ul()
        self.next_tick = reactor.callLater(1.0, self.tick)

    def stop(self):
        if self.next_tick is not None:
            self.next_tick.cancel()
            self.next_tick = None
        if self.next_dl_check is not None:
            self.next_dl_check.cancel()
            self.next_dl_check = None
        if self.next_ul_check is not None:
            self.next_ul_check.cancel()
            self.next_ul_check = None

    def set_dl_limit(self, limit):
        self.max_dl_bytes = limit

    def set_ul_limit(self, limit):
        self.max_ul_bytes = limit

    #throttling

    def check_dl(self):

        from twisted.internet import reactor

        self.next_dl_check = None

        if self.dl_bytes_this_second > self.max_dl_bytes:
            self.throttle_dl()
        else:
            self.next_dl_check = reactor.callLater(self.dl_check_interval, self.check_dl)
            self.dl_check_interval = min(self.dl_check_interval * 2, 1.0)

    def check_ul(self):

        from twisted.internet import reactor

        self.next_ul_check = None

        if self.ul_bytes_this_second > self.max_ul_bytes:
            self.throttle_ul()
        else:
            self.next_ul_check = reactor.callLater(self.ul_check_interval, self.check_ul)
            self.ul_check_interval = min(self.ul_check_interval * 2, 1.0)

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

    #deprecated

    def ul_wait_time(self):
        return 0

    def dl_wait_time(self):
        return 0

    #called by protocols

    def report_dl_bytes(self, num_bytes):
        self.dl_bytes_this_second += num_bytes
        self.total_dl_bytes += num_bytes

    def report_ul_bytes(self, num_bytes):
        self.ul_bytes_this_second += num_bytes
        self.total_ul_bytes += num_bytes

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