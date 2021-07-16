# import unittest
# from shutil import rmtree
# from tempfile import mkdtemp
#
# from lbry.wallet.server.history import History
# from lbry.wallet.server.storage import LevelDB
#
#
# # dumped from a real history database. Aside from the state, all records are <hashX><flush_count>: <value>
# STATE_RECORD = (b'state\x00\x00', b"{'flush_count': 21497, 'comp_flush_count': -1, 'comp_cursor': -1, 'db_version': 0}")
# UNMIGRATED_RECORDS = {
#     '00538b2cbe4a5f1be2dc320241': 'f5ed500142ee5001',
#     '00538b48def1904014880501f2': 'b9a52a01baa52a01',
#     '00538cdcf989b74de32c5100ca': 'c973870078748700',
#     '00538d42d5df44603474284ae1': 'f5d9d802',
#     '00538d42d5df44603474284ae2': '75dad802',
#     '00538ebc879dac6ddbee9e0029': '3ca42f0042a42f00',
#     '00538ed1d391327208748200bc': '804e7d00af4e7d00',
#     '00538f3de41d9e33affa0300c2': '7de8810086e88100',
#     '00539007f87792d98422c505a5': '8c5a7202445b7202',
#     '0053902cf52ee9682d633b0575': 'eb0f64026c106402',
#     '005390e05674571551632205a2': 'a13d7102e13d7102',
#     '0053914ef25a9ceed927330584': '78096902960b6902',
#     '005391768113f69548f37a01b1': 'a5b90b0114ba0b01',
#     '005391a289812669e5b44c02c2': '33da8a016cdc8a01',
# }
#
#
# class TestHistoryDBMigration(unittest.TestCase):
#     def test_migrate_flush_count_from_16_to_32_bits(self):
#         self.history = History()
#         tmpdir = mkdtemp()
#         self.addCleanup(lambda: rmtree(tmpdir))
#         LevelDB.import_module()
#         db = LevelDB(tmpdir, 'hist', True)
#         with db.write_batch() as batch:
#             for key, value in UNMIGRATED_RECORDS.items():
#                 batch.put(bytes.fromhex(key), bytes.fromhex(value))
#             batch.put(*STATE_RECORD)
#         self.history.db = db
#         self.history.read_state()
#         self.assertEqual(21497, self.history.flush_count)
#         self.assertEqual(0, self.history.db_version)
#         self.assertTrue(self.history.needs_migration)
#         self.history.migrate()
#         self.assertFalse(self.history.needs_migration)
#         self.assertEqual(1, self.history.db_version)
#         for idx, (key, value) in enumerate(sorted(db.iterator())):
#             if key == b'state\x00\x00':
#                 continue
#             key, counter = key[:-4], key[-4:]
#             expected_value = UNMIGRATED_RECORDS[key.hex() + counter.hex()[-4:]]
#             self.assertEqual(value.hex(), expected_value)
#
#
# if __name__ == '__main__':
#     unittest.main()
