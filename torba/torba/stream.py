import asyncio


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
            return self._on_data(data)

    def _add_error(self, exception):
        if self.can_fire and self._on_error is not None:
            return self._on_error(exception)

    def _close(self):
        try:
            if self.can_fire and self._on_done is not None:
                return self._on_done()
        finally:
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
        next_sub = self._first_subscription
        while next_sub is not None:
            subscription = next_sub
            next_sub = next_sub._next
            yield subscription

    def _notify_and_ensure_future(self, notify):
        tasks = []
        for subscription in self._iterate_subscriptions:
            maybe_coroutine = notify(subscription)
            if asyncio.iscoroutine(maybe_coroutine):
                tasks.append(maybe_coroutine)
        if tasks:
            return asyncio.ensure_future(asyncio.wait(tasks))
        else:
            f = asyncio.get_event_loop().create_future()
            f.set_result(None)
            return f

    def add(self, event):
        return self._notify_and_ensure_future(
            lambda subscription: subscription._add(event)
        )

    def add_error(self, exception):
        return self._notify_and_ensure_future(
            lambda subscription: subscription._add_error(exception)
        )

    def close(self):
        for subscription in self._iterate_subscriptions:
            subscription._close()

    def _cancel(self, subscription):
        previous = subscription._previous
        next_sub = subscription._next
        if previous is None:
            self._first_subscription = next_sub
        else:
            previous._next = next_sub
        if next_sub is None:
            self._last_subscription = previous
        else:
            next_sub._previous = previous
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

    def where(self, condition) -> asyncio.Future:
        future = asyncio.get_event_loop().create_future()

        def where_test(value):
            if condition(value):
                self._cancel_and_callback(subscription, future, value)

        subscription = self.listen(
            where_test,
            lambda exception: self._cancel_and_error(subscription, future, exception)
        )

        return future

    @property
    def first(self):
        future = asyncio.get_event_loop().create_future()
        subscription = self.listen(
            lambda value: self._cancel_and_callback(subscription, future, value),
            lambda exception: self._cancel_and_error(subscription, future, exception)
        )
        return future

    @staticmethod
    def _cancel_and_callback(subscription: BroadcastSubscription, future: asyncio.Future, value):
        subscription.cancel()
        future.set_result(value)

    @staticmethod
    def _cancel_and_error(subscription: BroadcastSubscription, future: asyncio.Future, exception):
        subscription.cancel()
        future.set_exception(exception)
