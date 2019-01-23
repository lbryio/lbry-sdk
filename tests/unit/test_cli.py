import contextlib
from io import StringIO
import unittest

from lbrynet.extras.cli import normalize_value, main
from lbrynet.extras.system_info import get_platform


class CLITest(unittest.TestCase):
    def test_guess_type(self):
        self.assertEqual('0.3.8', normalize_value('0.3.8'))
        self.assertEqual('0.3', normalize_value('0.3'))
        self.assertEqual(3, normalize_value('3'))
        self.assertEqual(3, normalize_value(3))

        self.assertEqual(
            'VdNmakxFORPSyfCprAD/eDDPk5TY9QYtSA==',
            normalize_value('VdNmakxFORPSyfCprAD/eDDPk5TY9QYtSA==')
        )

        self.assertTrue(normalize_value('TRUE'))
        self.assertTrue(normalize_value('true'))
        self.assertTrue(normalize_value('TrUe'))
        self.assertFalse(normalize_value('FALSE'))
        self.assertFalse(normalize_value('false'))
        self.assertFalse(normalize_value('FaLsE'))
        self.assertTrue(normalize_value(True))

        self.assertEqual('3', normalize_value('3', key="uri"))
        self.assertEqual('0.3', normalize_value('0.3', key="uri"))
        self.assertEqual('True', normalize_value('True', key="uri"))
        self.assertEqual('False', normalize_value('False', key="uri"))

        self.assertEqual('3', normalize_value('3', key="file_name"))
        self.assertEqual('3', normalize_value('3', key="name"))
        self.assertEqual('3', normalize_value('3', key="download_directory"))
        self.assertEqual('3', normalize_value('3', key="channel_name"))

        self.assertEqual(3, normalize_value('3', key="some_other_thing"))

    def test_help_command(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            main(['help'])
        actual_output = actual_output.getvalue()
        self.assertIn('usage: lbrynet [--version] [-h]', actual_output)

    def test_help_for_command_command(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            main(['help', 'publish'])
        actual_output = actual_output.getvalue()
        self.assertIn('Make a new name claim and publish', actual_output)
        self.assertIn('Usage:', actual_output)

    def test_help_for_command_command_with_invalid_command(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            main(['help', 'publish1'])
        self.assertIn('Invalid command name', actual_output.getvalue())

    def test_version_command(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            main(['--version'])
        self.assertEqual(
            actual_output.getvalue().strip(),
            "lbrynet {lbrynet_version}".format(**get_platform())
        )

    def test_invalid_command(self):
        actual_output = StringIO()
        with contextlib.redirect_stderr(actual_output):
            try:
                main(['publish1'])
            except SystemExit:
                pass
        self.assertIn("invalid choice: 'publish1'", actual_output.getvalue())

    def test_valid_command_daemon_not_started(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            main(["publish", '--name=asd', '--bid=99'])
        self.assertEqual(
            actual_output.getvalue().strip(),
            "Could not connect to daemon. Are you sure it's running?"
        )

    @unittest.SkipTest
    def test_deprecated_command_daemon_not_started(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            main(["wallet_balance"])
        self.assertEqual(
            actual_output.getvalue().strip(),
            "wallet_balance is deprecated, using account_balance.\n"
            "Could not connect to daemon. Are you sure it's running?"
        )
