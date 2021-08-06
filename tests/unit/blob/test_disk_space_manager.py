import os
import unittest
import tempfile

import lbry.wallet
from lbry.conf import Config
from lbry.blob.disk_space_manager import DiskSpaceManager


class ConfigurationTests(unittest.TestCase):

    def test_space_calculation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.mkdir(os.path.join(temp_dir, 'blobfiles'))
            config = Config(
                data_dir=temp_dir,
                wallet_dir=temp_dir,
                config=os.path.join(temp_dir, 'settings.yml')
            )
            dsm = DiskSpaceManager(config)
            self.assertEqual(0, dsm.space_used_mb)
            with open(os.path.join(config.data_dir, 'blobfiles', '3mb-file'), 'w') as blob:
                blob.write('0' * 3 * 1024 * 1024)
            self.assertEqual(3, dsm.space_used_mb)
