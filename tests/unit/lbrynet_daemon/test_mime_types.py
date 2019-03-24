import unittest
from lbrynet.schema import mime_types


class TestMimeTypes(unittest.TestCase):
    def test_mp4_video(self):
        self.assertEqual("video/mp4", mime_types.guess_media_type("test.mp4"))
        self.assertEqual("video/mp4", mime_types.guess_media_type("test.MP4"))

    def test_x_ext_(self):
        self.assertEqual("application/x-ext-lbry", mime_types.guess_media_type("test.lbry"))
        self.assertEqual("application/x-ext-lbry", mime_types.guess_media_type("test.LBRY"))

    def test_octet_stream(self):
        self.assertEqual("application/octet-stream", mime_types.guess_media_type("test."))
        self.assertEqual("application/octet-stream", mime_types.guess_media_type("test"))
