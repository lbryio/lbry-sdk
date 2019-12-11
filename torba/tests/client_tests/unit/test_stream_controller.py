import asyncio

from torba.stream import StreamController
from torba.tasks import TaskGroup
from torba.testcase import AsyncioTestCase


class StreamControllerTestCase(AsyncioTestCase):
    def test_non_unique_events(self):
        events = []
        controller = StreamController()
        controller.stream.listen(on_data=events.append)
        controller.add("yo")
        controller.add("yo")
        self.assertListEqual(events, ["yo", "yo"])

    def test_unique_events(self):
        events = []
        controller = StreamController(merge_repeated_events=True)
        controller.stream.listen(on_data=events.append)
        controller.add("yo")
        controller.add("yo")
        self.assertListEqual(events, ["yo"])


class TaskGroupTestCase(AsyncioTestCase):
    async def test_stop_empty_set(self):
        group = TaskGroup()
        group.cancel()
        await asyncio.wait_for(group.done.wait(), timeout=0.5)
        self.assertTrue(group.done.is_set())