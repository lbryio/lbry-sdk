import os
import unittest
import tempfile

import lbry.wallet
from lbry.conf import Config
from lbry.blob.disk_space_manager import DiskSpaceManager


class ConfigurationTests(unittest.TestCase):

    def test_space_management(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.mkdir(os.path.join(temp_dir, 'blobfiles'))
            config = Config(
                blob_storage_limit=5,
                data_dir=temp_dir,
                wallet_dir=temp_dir,
                config=os.path.join(temp_dir, 'settings.yml'),
            )
            dsm = DiskSpaceManager(config)
            self.assertEqual(0, dsm.space_used_mb)
            for file_no in range(10):
                with open(os.path.join(config.data_dir, 'blobfiles', f'3mb-{file_no}'), 'w') as blob:
                    blob.write('0' * 1 * 1024 * 1024)
            self.assertEqual(10, dsm.space_used_mb)
            dsm.clean()
            self.assertEqual(5, dsm.space_used_mb)

