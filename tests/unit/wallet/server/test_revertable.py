import unittest
import tempfile
import shutil
from lbry.wallet.server.db.revertable import RevertableOpStack, RevertableDelete, RevertablePut, OpStackIntegrity
from lbry.wallet.server.db.prefixes import ClaimToTXOPrefixRow, HubDB


class TestRevertableOpStack(unittest.TestCase):
    def setUp(self):
        self.fake_db = {}
        self.stack = RevertableOpStack(self.fake_db.get)

    def tearDown(self) -> None:
        self.stack.clear()
        self.fake_db.clear()

    def process_stack(self):
        for op in self.stack:
            if op.is_put:
                self.fake_db[op.key] = op.value
            else:
                self.fake_db.pop(op.key)
        self.stack.clear()

    def update(self, key1: bytes, value1: bytes, key2: bytes, value2: bytes):
        self.stack.append_op(RevertableDelete(key1, value1))
        self.stack.append_op(RevertablePut(key2, value2))

    def test_simplify(self):
        key1 = ClaimToTXOPrefixRow.pack_key(b'\x01' * 20)
        key2 = ClaimToTXOPrefixRow.pack_key(b'\x02' * 20)
        key3 = ClaimToTXOPrefixRow.pack_key(b'\x03' * 20)
        key4 = ClaimToTXOPrefixRow.pack_key(b'\x04' * 20)

        val1 = ClaimToTXOPrefixRow.pack_value(1, 0, 1, 0, 1, False, 'derp')
        val2 = ClaimToTXOPrefixRow.pack_value(1, 0, 1, 0, 1, False, 'oops')
        val3 = ClaimToTXOPrefixRow.pack_value(1, 0, 1, 0, 1, False, 'other')

        # check that we can't delete a non existent value
        with self.assertRaises(OpStackIntegrity):
            self.stack.append_op(RevertableDelete(key1, val1))

        self.stack.append_op(RevertablePut(key1, val1))
        self.assertEqual(1, len(self.stack))
        self.stack.append_op(RevertableDelete(key1, val1))
        self.assertEqual(0, len(self.stack))

        self.stack.append_op(RevertablePut(key1, val1))
        self.assertEqual(1, len(self.stack))
        # try to delete the wrong value
        with self.assertRaises(OpStackIntegrity):
            self.stack.append_op(RevertableDelete(key2, val2))

        self.stack.append_op(RevertableDelete(key1, val1))
        self.assertEqual(0, len(self.stack))
        self.stack.append_op(RevertablePut(key2, val3))
        self.assertEqual(1, len(self.stack))

        self.process_stack()

        self.assertDictEqual({key2: val3}, self.fake_db)

        # check that we can't put on top of the existing stored value
        with self.assertRaises(OpStackIntegrity):
            self.stack.append_op(RevertablePut(key2, val1))

        self.assertEqual(0, len(self.stack))
        self.stack.append_op(RevertableDelete(key2, val3))
        self.assertEqual(1, len(self.stack))
        self.stack.append_op(RevertablePut(key2, val3))
        self.assertEqual(0, len(self.stack))

        self.update(key2, val3, key2, val1)
        self.assertEqual(2, len(self.stack))

        self.process_stack()
        self.assertDictEqual({key2: val1}, self.fake_db)

        self.update(key2, val1, key2, val2)
        self.assertEqual(2, len(self.stack))
        self.update(key2, val2, key2, val3)
        self.update(key2, val3, key2, val2)
        self.update(key2, val2, key2, val3)
        self.update(key2, val3, key2, val2)
        with self.assertRaises(OpStackIntegrity):
            self.update(key2, val3, key2, val2)
        self.update(key2, val2, key2, val3)
        self.assertEqual(2, len(self.stack))
        self.stack.append_op(RevertableDelete(key2, val3))
        self.process_stack()
        self.assertDictEqual({}, self.fake_db)

        self.stack.append_op(RevertablePut(key2, val3))
        self.process_stack()
        with self.assertRaises(OpStackIntegrity):
            self.update(key2, val2, key2, val2)
        self.update(key2, val3, key2, val2)
        self.assertDictEqual({key2: val3}, self.fake_db)
        undo = self.stack.get_undo_ops()
        self.process_stack()
        self.assertDictEqual({key2: val2}, self.fake_db)
        self.stack.apply_packed_undo_ops(undo)
        self.process_stack()
        self.assertDictEqual({key2: val3}, self.fake_db)


class TestRevertablePrefixDB(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db = HubDB(self.tmp_dir, cache_mb=1, max_open_files=32)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmp_dir)

    def test_rollback(self):
        name = 'derp'
        claim_hash1 = 20 * b'\x00'
        claim_hash2 = 20 * b'\x01'
        claim_hash3 = 20 * b'\x02'

        takeover_height = 10000000

        self.assertIsNone(self.db.claim_takeover.get(name))
        self.db.claim_takeover.stage_put((name,), (claim_hash1, takeover_height))
        self.assertIsNone(self.db.claim_takeover.get(name))
        self.assertEqual(10000000, self.db.claim_takeover.get_pending(name).height)

        self.db.commit(10000000)
        self.assertEqual(10000000, self.db.claim_takeover.get(name).height)

        self.db.claim_takeover.stage_delete((name,), (claim_hash1, takeover_height))
        self.db.claim_takeover.stage_put((name,), (claim_hash2, takeover_height + 1))
        self.db.claim_takeover.stage_delete((name,), (claim_hash2, takeover_height + 1))
        self.db.commit(10000001)
        self.assertIsNone(self.db.claim_takeover.get(name))
        self.db.claim_takeover.stage_put((name,), (claim_hash3, takeover_height + 2))
        self.db.commit(10000002)
        self.assertEqual(10000002, self.db.claim_takeover.get(name).height)

        self.db.claim_takeover.stage_delete((name,), (claim_hash3, takeover_height + 2))
        self.db.claim_takeover.stage_put((name,), (claim_hash2, takeover_height + 3))
        self.db.commit(10000003)
        self.assertEqual(10000003, self.db.claim_takeover.get(name).height)

        self.db.rollback(10000003)
        self.assertEqual(10000002, self.db.claim_takeover.get(name).height)
        self.db.rollback(10000002)
        self.assertIsNone(self.db.claim_takeover.get(name))
        self.db.rollback(10000001)
        self.assertEqual(10000000, self.db.claim_takeover.get(name).height)
        self.db.rollback(10000000)
        self.assertIsNone(self.db.claim_takeover.get(name))
