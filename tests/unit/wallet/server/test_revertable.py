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

        self.db.commit(10000000, b'\x00' * 32)
        self.assertEqual(10000000, self.db.claim_takeover.get(name).height)

        self.db.claim_takeover.stage_delete((name,), (claim_hash1, takeover_height))
        self.db.claim_takeover.stage_put((name,), (claim_hash2, takeover_height + 1))
        self.db.claim_takeover.stage_delete((name,), (claim_hash2, takeover_height + 1))
        self.db.commit(10000001, b'\x01' * 32)
        self.assertIsNone(self.db.claim_takeover.get(name))
        self.db.claim_takeover.stage_put((name,), (claim_hash3, takeover_height + 2))
        self.db.commit(10000002, b'\x02' * 32)
        self.assertEqual(10000002, self.db.claim_takeover.get(name).height)

        self.db.claim_takeover.stage_delete((name,), (claim_hash3, takeover_height + 2))
        self.db.claim_takeover.stage_put((name,), (claim_hash2, takeover_height + 3))
        self.db.commit(10000003, b'\x03' * 32)
        self.assertEqual(10000003, self.db.claim_takeover.get(name).height)

        self.db.rollback(10000003, b'\x03' * 32)
        self.assertEqual(10000002, self.db.claim_takeover.get(name).height)
        self.db.rollback(10000002, b'\x02' * 32)
        self.assertIsNone(self.db.claim_takeover.get(name))
        self.db.rollback(10000001, b'\x01' * 32)
        self.assertEqual(10000000, self.db.claim_takeover.get(name).height)
        self.db.rollback(10000000, b'\x00' * 32)
        self.assertIsNone(self.db.claim_takeover.get(name))

    def test_hub_db_iterator(self):
        name = 'derp'
        claim_hash0 = 20 * b'\x00'
        claim_hash1 = 20 * b'\x01'
        claim_hash2 = 20 * b'\x02'
        claim_hash3 = 20 * b'\x03'
        overflow_value = 0xffffffff
        self.db.claim_expiration.stage_put((99, 999, 0), (claim_hash0, name))
        self.db.claim_expiration.stage_put((100, 1000, 0), (claim_hash1, name))
        self.db.claim_expiration.stage_put((100, 1001, 0), (claim_hash2, name))
        self.db.claim_expiration.stage_put((101, 1002, 0), (claim_hash3, name))
        self.db.claim_expiration.stage_put((overflow_value - 1, 1003, 0), (claim_hash3, name))
        self.db.claim_expiration.stage_put((overflow_value, 1004, 0), (claim_hash3, name))
        self.db.tx_num.stage_put((b'\x00' * 32,), (101,))
        self.db.claim_takeover.stage_put((name,), (claim_hash3, 101))
        self.db.db_state.stage_put((), (b'n?\xcf\x12\x99\xd4\xec]y\xc3\xa4\xc9\x1dbJJ\xcf\x9e.\x17=\x95\xa1\xa0POgvihuV', 0, 1, b'VuhivgOP\xa0\xa1\x95=\x17.\x9e\xcfJJb\x1d\xc9\xa4\xc3y]\xec\xd4\x99\x12\xcf?n', 1, 0, 1, 7, 1, -1, -1, 0))
        self.db.unsafe_commit()

        state = self.db.db_state.get()
        self.assertEqual(b'n?\xcf\x12\x99\xd4\xec]y\xc3\xa4\xc9\x1dbJJ\xcf\x9e.\x17=\x95\xa1\xa0POgvihuV', state.genesis)

        self.assertListEqual(
            [], list(self.db.claim_expiration.iterate(prefix=(98,)))
        )
        self.assertListEqual(
            list(self.db.claim_expiration.iterate(start=(98,), stop=(99,))),
            list(self.db.claim_expiration.iterate(prefix=(98,)))
        )
        self.assertListEqual(
            list(self.db.claim_expiration.iterate(start=(99,), stop=(100,))),
            list(self.db.claim_expiration.iterate(prefix=(99,)))
        )
        self.assertListEqual(
            [
                ((99, 999, 0), (claim_hash0, name)),
            ], list(self.db.claim_expiration.iterate(prefix=(99,)))
        )
        self.assertListEqual(
            [
                ((100, 1000, 0), (claim_hash1, name)),
                ((100, 1001, 0), (claim_hash2, name))
            ], list(self.db.claim_expiration.iterate(prefix=(100,)))
        )
        self.assertListEqual(
            list(self.db.claim_expiration.iterate(start=(100,), stop=(101,))),
            list(self.db.claim_expiration.iterate(prefix=(100,)))
        )
        self.assertListEqual(
            [
                ((overflow_value - 1, 1003, 0), (claim_hash3, name))
            ], list(self.db.claim_expiration.iterate(prefix=(overflow_value - 1,)))
        )
        self.assertListEqual(
            [
                ((overflow_value, 1004, 0), (claim_hash3, name))
            ], list(self.db.claim_expiration.iterate(prefix=(overflow_value,)))
        )
