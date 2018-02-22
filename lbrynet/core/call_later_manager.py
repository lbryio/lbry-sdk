class CallLaterManager(object):
    _callLater = None
    _pendingCallLaters = []

    @classmethod
    def _cancel(cls, call_later):
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
            cls._pendingCallLaters.remove(call_later)
            return reason
        return cancel

    @classmethod
    def stop(cls):
        """
        Cancel any callLaters that are still running
        """

        from twisted.internet import defer
        while cls._pendingCallLaters:
            canceller = cls._cancel(cls._pendingCallLaters[0])
            try:
                canceller()
            except (defer.CancelledError, defer.AlreadyCalledError):
                pass

    @classmethod
    def call_later(cls, when, what, *args, **kwargs):
        """
        Schedule a call later and get a canceller callback function

        :param when: (float) delay in seconds
        :param what: (callable)
        :param args: (*tuple) args to be passed to the callable
        :param kwargs: (**dict) kwargs to be passed to the callable

        :return: (tuple) twisted.internet.base.DelayedCall object, canceller function
        """

        call_later = cls._callLater(when, what, *args, **kwargs)
        canceller = cls._cancel(call_later)
        cls._pendingCallLaters.append(call_later)
        return call_later, canceller

    @classmethod
    def setup(cls, callLater):
        """
        Setup the callLater function to use, supports the real reactor as well as task.Clock

        :param callLater: (IReactorTime.callLater)
        """
        cls._callLater = callLater
