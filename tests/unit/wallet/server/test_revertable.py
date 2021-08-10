import unittest
from lbry.wallet.server.db.revertable import RevertableOpStack, RevertableDelete, RevertablePut, OpStackIntegrity
from lbry.wallet.server.db.prefixes import Prefixes


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
        key1 = Prefixes.claim_to_txo.pack_key(b'\x01' * 20)
        key2 = Prefixes.claim_to_txo.pack_key(b'\x02' * 20)
        key3 = Prefixes.claim_to_txo.pack_key(b'\x03' * 20)
        key4 = Prefixes.claim_to_txo.pack_key(b'\x04' * 20)

        val1 = Prefixes.claim_to_txo.pack_value(1, 0, 1, 0, 1, 0, 'derp')
        val2 = Prefixes.claim_to_txo.pack_value(1, 0, 1, 0, 1, 0, 'oops')
        val3 = Prefixes.claim_to_txo.pack_value(1, 0, 1, 0, 1, 0, 'other')

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

