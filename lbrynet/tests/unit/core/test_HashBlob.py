from lbrynet.blob import BlobFile
from lbrynet.core.Error import DownloadCanceledError, InvalidDataError


from lbrynet.tests.util import mk_db_and_blob_dir, rm_db_and_blob_dir, random_lbry_hash
from twisted.trial import unittest
from twisted.internet import defer


class BlobFileTest(unittest.TestCase):
    def setUp(self):
        self.db_dir, self.blob_dir = mk_db_and_blob_dir()
        self.fake_content_len = 64
        self.fake_content = bytearray('0'*self.fake_content_len)
        self.fake_content_hash = '53871b26a08e90cb62142f2a39f0b80de41792322b0ca560' \
                                 '2b6eb7b5cf067c49498a7492bb9364bbf90f40c1c5412105'

    def tearDown(self):
        rm_db_and_blob_dir(self.db_dir, self.blob_dir)

    @defer.inlineCallbacks
    def test_good_write_and_read(self):
        # test a write that should succeed
        blob_file = BlobFile(self.blob_dir, self.fake_content_hash, self.fake_content_len)
        self.assertFalse(blob_file.verified)

        writer, finished_d = blob_file.open_for_writing(peer=1)
        writer.write(self.fake_content)
        writer.close()
        out = yield finished_d
        self.assertTrue(isinstance(out, BlobFile))
        self.assertTrue(out.verified)
        self.assertEqual(self.fake_content_len, out.get_length())

        # read from the instance used to write to, and verify content
        f = blob_file.open_for_reading()
        c = f.read()
        self.assertEqual(c, self.fake_content)
        self.assertFalse(out.is_downloading())

        # read from newly declared instance, and verify content
        del blob_file
        blob_file = BlobFile(self.blob_dir, self.fake_content_hash, self.fake_content_len)
        self.assertTrue(blob_file.verified)
        f = blob_file.open_for_reading()
        self.assertEqual(1, blob_file.readers)
        c = f.read()
        self.assertEqual(c, self.fake_content)

        # close reader
        f.close()
        self.assertEqual(0, blob_file.readers)


    @defer.inlineCallbacks
    def test_delete(self):
        blob_file = BlobFile(self.blob_dir, self.fake_content_hash, self.fake_content_len)
        writer, finished_d = blob_file.open_for_writing(peer=1)
        writer.write(self.fake_content)
        out = yield finished_d
        out = yield blob_file.delete()

        blob_file = BlobFile(self.blob_dir, self.fake_content_hash)
        self.assertFalse(blob_file.verified)

    @defer.inlineCallbacks
    def test_delete_fail(self):
        # deletes should fail if being written to
        blob_file = BlobFile(self.blob_dir, self.fake_content_hash, self.fake_content_len)
        writer, finished_d = blob_file.open_for_writing(peer=1)
        yield self.assertFailure(blob_file.delete(), ValueError)
        writer.write(self.fake_content)
        writer.close()

        # deletes should fail if being read and not closed
        blob_file = BlobFile(self.blob_dir, self.fake_content_hash, self.fake_content_len)
        self.assertTrue(blob_file.verified)
        f = blob_file.open_for_reading()
        yield self.assertFailure(blob_file.delete(), ValueError)

    @defer.inlineCallbacks
    def test_too_much_write(self):
        # writing too much data should result in failure
        expected_length = 16
        content = bytearray('0'*32)
        blob_hash = random_lbry_hash()
        blob_file = BlobFile(self.blob_dir, blob_hash, expected_length)
        writer, finished_d = blob_file.open_for_writing(peer=1)
        writer.write(content)
        out = yield self.assertFailure(finished_d, InvalidDataError)

    @defer.inlineCallbacks
    def test_bad_hash(self):
        # test a write that should fail because its content's hash
        # does not equal the blob_hash
        length = 64
        content = bytearray('0'*length)
        blob_hash = random_lbry_hash()
        blob_file = BlobFile(self.blob_dir, blob_hash, length)
        writer, finished_d = blob_file.open_for_writing(peer=1)
        writer.write(content)
        yield self.assertFailure(finished_d, InvalidDataError)

    @defer.inlineCallbacks
    def test_close_on_incomplete_write(self):
        # write all but 1 byte of data,
        blob_file = BlobFile(self.blob_dir, self.fake_content_hash, self.fake_content_len)
        writer, finished_d = blob_file.open_for_writing(peer=1)
        writer.write(self.fake_content[:self.fake_content_len-1])
        writer.close()
        yield self.assertFailure(finished_d, DownloadCanceledError)

        # writes after close will throw a IOError exception
        with self.assertRaises(IOError):
            writer.write(self.fake_content)

        # another call to close will do nothing
        writer.close()

        # file should not exist, since we did not finish write
        blob_file_2 = BlobFile(self.blob_dir, self.fake_content_hash, self.fake_content_len)
        out = blob_file_2.open_for_reading()
        self.assertEqual(None, out)

    @defer.inlineCallbacks
    def test_multiple_writers(self):
        # start first writer and write half way, and then start second writer and write everything
        blob_hash = self.fake_content_hash
        blob_file = BlobFile(self.blob_dir, blob_hash, self.fake_content_len)
        writer_1, finished_d_1 = blob_file.open_for_writing(peer=1)
        writer_1.write(self.fake_content[:self.fake_content_len/2])

        writer_2, finished_d_2 = blob_file.open_for_writing(peer=2)
        writer_2.write(self.fake_content)
        out_2 = yield finished_d_2
        out_1 = yield self.assertFailure(finished_d_1, DownloadCanceledError)

        self.assertTrue(isinstance(out_2, BlobFile))
        self.assertTrue(out_2.verified)
        self.assertEqual(self.fake_content_len, out_2.get_length())

        f = blob_file.open_for_reading()
        c = f.read()
        self.assertEqual(self.fake_content_len, len(c))
        self.assertEqual(bytearray(c), self.fake_content)


