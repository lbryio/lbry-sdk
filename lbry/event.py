import time
import asyncio
import threading
import logging
from queue import Empty
from multiprocessing import Queue


log = logging.getLogger(__name__)


class BroadcastSubscription:

    def __init__(self, controller: 'EventController', on_data, on_error, on_done):
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


class EventController:

    def __init__(self, merge_repeated_events=False):
        self.stream = EventStream(self)
        self._first_subscription = None
        self._last_subscription = None
        self._last_event = None
        self._merge_repeated = merge_repeated_events

    @property
    def has_listener(self):
        return self._first_subscription is not None

    @property
    def _iterate_subscriptions(self):
        next_sub = self._first_subscription
        while next_sub is not None:
            subscription = next_sub
            yield subscription
            next_sub = next_sub._next

    async def _notify(self, notify, *args):
        try:
            maybe_coroutine = notify(*args)
            if maybe_coroutine is not None and asyncio.iscoroutine(maybe_coroutine):
                await maybe_coroutine
        except Exception as e:
            log.exception(e)
            raise

    async def add(self, event):
        if self._merge_repeated and event == self._last_event:
            return
        self._last_event = event
        for subscription in self._iterate_subscriptions:
            await self._notify(subscription._add, event)

    async def add_all(self, events):
        for event in events:
            await self.add(event)

    async def add_error(self, exception):
        for subscription in self._iterate_subscriptions:
            await self._notify(subscription._add_error, exception)

    async def close(self):
        for subscription in self._iterate_subscriptions:
            await self._notify(subscription._close)

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


class EventStream:

    def __init__(self, controller: EventController):
        self._controller = controller

    def listen(self, on_data, on_error=None, on_done=None) -> BroadcastSubscription:
        return self._controller._listen(on_data, on_error, on_done)

    def where(self, condition) -> asyncio.Future:
        future = asyncio.get_running_loop().create_future()

        def where_test(value):
            if condition(value):
                self._cancel_and_callback(subscription, future, value)

        subscription = self.listen(
            where_test,
            lambda exception: self._cancel_and_error(subscription, future, exception)
        )

        return future

    @property
    def first(self) -> asyncio.Future:
        future = asyncio.get_event_loop().create_future()
        subscription = self.listen(
            lambda value: not future.done() and self._cancel_and_callback(subscription, future, value),
            lambda exception: not future.done() and self._cancel_and_error(subscription, future, exception)
        )
        return future

    @property
    def last(self) -> asyncio.Future:
        future = asyncio.get_event_loop().create_future()
        value = None

        def update_value(_value):
            nonlocal value
            value = _value

        subscription = self.listen(
            update_value,
            lambda exception: not future.done() and self._cancel_and_error(subscription, future, exception),
            lambda: not future.done() and self._cancel_and_callback(subscription, future, value),
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


class EventQueuePublisher(threading.Thread):

    STOP = 'STOP'

    def __init__(self, queue: Queue, event_controller: EventController):
        super().__init__()
        self.queue = queue
        self.event_controller = event_controller
        self.loop = None

    @staticmethod
    def message_to_event(message):
        return message

    def start(self):
        self.loop = asyncio.get_running_loop()
        super().start()

    def run(self):
        queue_get_timeout = 0.2
        buffer_drain_size = 100
        buffer_drain_timeout = 0.1

        buffer = []
        last_drained_ms_ago = time.perf_counter()
        while True:

            try:
                msg = self.queue.get(timeout=queue_get_timeout)
                if msg != self.STOP:
                    buffer.append(msg)
            except Empty:
                msg = None

            drain = any((
                len(buffer) >= buffer_drain_size,
                (time.perf_counter() - last_drained_ms_ago) >= buffer_drain_timeout,
                msg == self.STOP
            ))
            if drain and buffer:
                asyncio.run_coroutine_threadsafe(
                    self.event_controller.add_all([
                        self.message_to_event(msg) for msg in buffer
                    ]), self.loop
                )
                buffer.clear()
                last_drained_ms_ago = time.perf_counter()

            if msg == self.STOP:
                return

    def stop(self):
        self.queue.put(self.STOP)
        self.join()

    def __enter__(self):
        self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
