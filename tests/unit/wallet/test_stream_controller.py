from lbry.wallet.stream import StreamController
from lbry.wallet.tasks import TaskGroup
from lbry.testcase import AsyncioTestCase


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

    async def test_cancel_sets_it_done(self):
        group = TaskGroup()
        group.cancel()
        self.assertTrue(group.done.is_set())
