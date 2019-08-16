from torba.stream import StreamController
from torba.testcase import AsyncioTestCase


class StreamControllerTestCase(AsyncioTestCase):
    def test_non_unique_events(self):
        events = []
        controller = StreamController()
        controller.stream.listen(on_data=events.append)
        controller.add("yo")
        controller.add("yo")
        self.assertEqual(events, ["yo", "yo"])

    def test_unique_events(self):
        events = []
        controller = StreamController(merge_repeated_events=True)
        controller.stream.listen(on_data=events.append)
        controller.add("yo")
        controller.add("yo")
        self.assertEqual(events, ["yo"])
