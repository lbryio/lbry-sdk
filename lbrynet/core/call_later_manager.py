import logging

log = logging.getLogger()

MIN_DELAY = 0.0
MAX_DELAY = 0.01
DELAY_INCREMENT = 0.0001
QUEUE_SIZE_THRESHOLD = 100


class CallLaterManager(object):
    def __init__(self, callLater):
        """
        :param callLater: (IReactorTime.callLater)
        """

        self._callLater = callLater
        self._pendingCallLaters = []
        self._delay = MIN_DELAY

    def get_min_delay(self):
        self._pendingCallLaters = [cl for cl in self._pendingCallLaters if cl.active()]
        queue_size = len(self._pendingCallLaters)
        if queue_size > QUEUE_SIZE_THRESHOLD:
            self._delay = min((self._delay + DELAY_INCREMENT), MAX_DELAY)
        else:
            self._delay = max((self._delay - 2.0 * DELAY_INCREMENT), MIN_DELAY)
        return self._delay

    def _cancel(self, call_later):
        """
        :param call_later: DelayedCall
        :return: (callable) canceller function
        """

        def cancel(reason=None):
            """
            :param reason: reason for cancellation, this is returned after cancelling the DelayedCall
            :return: reason
            """

            if call_later.active():
                call_later.cancel()
            if call_later in self._pendingCallLaters:
                self._pendingCallLaters.remove(call_later)
            return reason
        return cancel

    def stop(self):
        """
        Cancel any callLaters that are still running
        """

        from twisted.internet import defer
        while self._pendingCallLaters:
            canceller = self._cancel(self._pendingCallLaters[0])
            try:
                canceller()
            except (defer.CancelledError, defer.AlreadyCalledError, ValueError):
                pass

    def call_later(self, when, what, *args, **kwargs):
        """
        Schedule a call later and get a canceller callback function

        :param when: (float) delay in seconds
        :param what: (callable)
        :param args: (*tuple) args to be passed to the callable
        :param kwargs: (**dict) kwargs to be passed to the callable

        :return: (tuple) twisted.internet.base.DelayedCall object, canceller function
        """

        call_later = self._callLater(when, what, *args, **kwargs)
        canceller = self._cancel(call_later)
        self._pendingCallLaters.append(call_later)
        return call_later, canceller

    def call_soon(self, what, *args, **kwargs):
        delay = self.get_min_delay()
        return self.call_later(delay, what, *args, **kwargs)
