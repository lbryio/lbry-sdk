from twisted.internet.defer import Deferred
from twisted.python.failure import Failure


class BroadcastSubscription:

    def __init__(self, controller, on_data, on_error, on_done):
        self._controller = controller
        self._previous = self._next = None
        self._on_data = on_data
        self._on_error = on_error
        self._on_done = on_done
        self.is_paused = False
        self.is_canceled = False
        self.is_closed = False

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def cancel(self):
        self._controller._cancel(self)
        self.is_canceled = True

    @property
    def can_fire(self):
        return not any((self.is_paused, self.is_canceled, self.is_closed))

    def _add(self, data):
        if self.can_fire and self._on_data is not None:
            self._on_data(data)

    def _add_error(self, error, traceback):
        if self.can_fire and self._on_error is not None:
            self._on_error(error, traceback)

    def _close(self):
        if self.can_fire and self._on_done is not None:
            self._on_done()
        self.is_closed = True


class StreamController:

    def __init__(self):
        self.stream = Stream(self)
        self._first_subscription = None
        self._last_subscription = None

    @property
    def has_listener(self):
        return self._first_subscription is not None

    @property
    def _iterate_subscriptions(self):
        next = self._first_subscription
        while next is not None:
            subscription = next
            next = next._next
            yield subscription

    def add(self, event):
        for subscription in self._iterate_subscriptions:
            subscription._add(event)

    def add_error(self, error, traceback):
        for subscription in self._iterate_subscriptions:
            subscription._add_error(error, traceback)

    def close(self):
        for subscription in self._iterate_subscriptions:
            subscription._close()

    def _cancel(self, subscription):
        previous = subscription._previous
        next = subscription._next
        if previous is None:
            self._first_subscription = next
        else:
            previous._next = next
        if next is None:
            self._last_subscription = previous
        else:
            next._previous = previous
        subscription._next = subscription._previous = subscription

    def _listen(self, on_data, on_error, on_done):
        subscription = BroadcastSubscription(self, on_data, on_error, on_done)
        old_last = self._last_subscription
        self._last_subscription = subscription
        subscription._previous = old_last
        subscription._next = None
        if old_last is None:
            self._first_subscription = subscription
        else:
            old_last._next = subscription
        return subscription


class Stream:

    def __init__(self, controller):
        self._controller = controller

    def listen(self, on_data, on_error=None, on_done=None):
        return self._controller._listen(on_data, on_error, on_done)

    @property
    def first(self):
        deferred = Deferred()
        subscription = self.listen(
            lambda value: self._cancel_and_callback(subscription, deferred, value),
            lambda error, traceback: self._cancel_and_error(subscription, deferred, error, traceback)
        )
        return deferred

    @staticmethod
    def _cancel_and_callback(subscription, deferred, value):
        subscription.cancel()
        deferred.callback(value)

    @staticmethod
    def _cancel_and_error(subscription, deferred, error, traceback):
        subscription.cancel()
        deferred.errback(Failure(error, exc_tb=traceback))
