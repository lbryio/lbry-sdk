class Delay(object):
    maxToSendDelay = 10 ** -3  # 0.05
    minToSendDelay = 10 ** -5  # 0.01

    def __init__(self, start=0, getTime=None):
        self._next = start
        if not getTime:
            from time import time as getTime
        self._getTime = getTime

    # TODO: explain why this logic is like it is. And add tests that
    #       show that it actually does what it needs to do.
    def __call__(self):
        ts = self._getTime()
        if ts >= self._next:
            delay = self.minToSendDelay
            self._next = ts + self.minToSendDelay
        else:
            delay = (self._next - ts) + self.maxToSendDelay
            self._next += self.maxToSendDelay
        return delay
