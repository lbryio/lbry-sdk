import unittest
import tempfile
import os

from lbry.schema.mime_types import guess_media_type

class MediaTypeTests(unittest.TestCase):
    def test_guess_media_type_from_path_only(self):
        kind = guess_media_type('/tmp/test.mkv')
        self.assertEqual(kind, ('video/x-matroska', 'video'))

    def test_defaults_for_no_extension(self):
        kind = guess_media_type('/tmp/test')
        self.assertEqual(kind, ('application/octet-stream', 'binary'))

    def test_defaults_for_unknown_extension(self):
        kind = guess_media_type('/tmp/test.unk')
        self.assertEqual(kind, ('application/x-ext-unk', 'binary'))

    def test_spoofed_unknown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file = os.path.join(temp_dir, 'spoofed_unknown.txt')
            with open(file, 'wb') as fd:
                bytes_lz4 = bytearray([0x04,0x22,0x4d,0x18])
                fd.write(bytes_lz4)
                fd.close()

            kind = guess_media_type(file)
            self.assertEqual(kind, ('application/x-ext-lz4', 'binary'))

    def test_spoofed_known(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file = os.path.join(temp_dir, 'spoofed_known.avi')
            with open(file, 'wb') as fd:
                bytes_zip = bytearray([0x50,0x4b,0x03,0x06])
                fd.write(bytes_zip)
                fd.close()

            kind = guess_media_type(file)
            self.assertEqual(kind, ('application/zip', 'binary'))

    def test_spoofed_synonym(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file = os.path.join(temp_dir, 'spoofed_known.cbz')
            with open(file, 'wb') as fd:
                bytes_zip = bytearray([0x50,0x4b,0x03,0x06])
                fd.write(bytes_zip)
                fd.close()

            kind = guess_media_type(file)
            self.assertEqual(kind, ('application/vnd.comicbook+zip', 'document'))
