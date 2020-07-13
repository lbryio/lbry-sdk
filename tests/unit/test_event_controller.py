import asyncio
import logging
import multiprocessing as mp
from unittest import skip
from concurrent.futures import ThreadPoolExecutor

from lbry.testcase import AsyncioTestCase
from lbry.event import EventController, EventQueuePublisher
from lbry.tasks import TaskGroup


class StreamControllerTestCase(AsyncioTestCase):

    async def test_non_unique_events(self):
        events = []
        controller = EventController()
        controller.stream.listen(events.append)
        await controller.add("yo")
        await controller.add("yo")
        self.assertListEqual(events, ["yo", "yo"])

    async def test_unique_events(self):
        events = []
        controller = EventController(merge_repeated_events=True)
        controller.stream.listen(events.append)
        await controller.add("yo")
        await controller.add("yo")
        self.assertListEqual(events, ["yo"])

    async def test_sync_listener_errors(self):
        def bad_listener(_):
            raise ValueError('bad')
        controller = EventController()
        controller.stream.listen(bad_listener)
        with self.assertRaises(ValueError), self.assertLogs():
            await controller.add("yo")

    async def test_async_listener_errors(self):
        async def bad_listener(_):
            raise ValueError('bad')
        controller = EventController()
        controller.stream.listen(bad_listener)
        with self.assertRaises(ValueError), self.assertLogs():
            await controller.add("yo")

    async def test_first_event(self):
        controller = EventController()
        first = controller.stream.first
        await controller.add("one")
        second = controller.stream.first
        await controller.add("two")
        self.assertEqual("one", await first)
        self.assertEqual("two", await second)

    async def test_last_event(self):
        controller = EventController()
        last = controller.stream.last
        await controller.add("one")
        await controller.add("two")
        await controller.close()
        self.assertEqual("two", await last)

    async def test_race_condition_during_subscription_iteration(self):
        controller = EventController()
        sub1 = controller.stream.listen(print)
        sub2 = controller.stream.listen(print)
        sub3 = controller.stream.listen(print)

        # normal iteration
        i = iter(controller._iterate_subscriptions)
        self.assertEqual(next(i, None), sub1)
        self.assertEqual(next(i, None), sub2)
        self.assertEqual(next(i, None), sub3)
        self.assertEqual(next(i, None), None)

        # subscription canceled immediately after it's iterated over
        i = iter(controller._iterate_subscriptions)
        self.assertEqual(next(i, None), sub1)
        self.assertEqual(next(i, None), sub2)
        sub2.cancel()
        self.assertEqual(next(i, None), sub3)
        self.assertEqual(next(i, None), None)

        # subscription canceled immediately before it's iterated over
        self.assertEqual(list(controller._iterate_subscriptions), [sub1, sub3])  # precondition
        i = iter(controller._iterate_subscriptions)
        self.assertEqual(next(i, None), sub1)
        sub3.cancel()
        self.assertEqual(next(i, None), None)


class TestEventQueuePublisher(AsyncioTestCase):

    async def test_event_buffering_avoids_overloading_asyncio(self):
        threads = 3
        generate_events = 2000
        expected_event_count = (threads * generate_events)-1

        queue = mp.Queue()
        executor = ThreadPoolExecutor(max_workers=threads)
        controller = EventController()
        events = []

        async def event_logger(e):
            await asyncio.sleep(0)
            events.append(e)

        controller.stream.listen(event_logger)
        until_all_consumed = controller.stream.where(lambda _: len(events) == expected_event_count)

        def event_producer(q, j):
            for i in range(generate_events):
                q.put(f'foo-{i}-{j}')

        with EventQueuePublisher(queue, controller), self.assertLogs() as logs:
            # assertLogs() requires that at least one message is logged
            # this is that one message:
            logging.getLogger().info("placeholder")
            await asyncio.wait([
                self.loop.run_in_executor(executor, event_producer, queue, j)
                for j in range(threads)
            ])
            await until_all_consumed
            # assert that there were no WARNINGs from asyncio about slow tasks
            # (should have exactly 1 log which is the placeholder above)
            self.assertEqual(['INFO:root:placeholder'], logs.output)


class TaskGroupTestCase(AsyncioTestCase):

    async def test_cancel_sets_it_done(self):
        group = TaskGroup()
        group.cancel()
        self.assertTrue(group.done.is_set())
