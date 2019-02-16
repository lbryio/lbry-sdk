import unittest
from lbrynet.extras.daemon import mime_types


class TestMimeTypes(unittest.TestCase):
    def test_mp4_video(self):
        self.assertEqual("video/mp4", mime_types.guess_media_type("test.mp4"))

    def test_x_ext_(self):
        self.assertEqual("application/x-ext-lbry", mime_types.guess_media_type("test.lbry"))

    def test_octet_stream(self):
        self.assertEqual("application/octet-stream", mime_types.guess_media_type("test."))
        self.assertEqual("application/octet-stream", mime_types.guess_media_type("test"))
