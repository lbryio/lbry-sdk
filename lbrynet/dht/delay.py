import time


class Delay(object):
    maxToSendDelay = 10 ** -3  # 0.05
    minToSendDelay = 10 ** -5  # 0.01

    def __init__(self, start=0):
        self._next = start

    # TODO: explain why this logic is like it is. And add tests that
    #       show that it actually does what it needs to do.
    def __call__(self):
        ts = time.time()
        delay = 0
        if ts >= self._next:
            delay = self.minToSendDelay
            self._next = ts + self.minToSendDelay
        else:
            delay = (self._next - ts) + self.maxToSendDelay
            self._next += self.maxToSendDelay
        return delay
