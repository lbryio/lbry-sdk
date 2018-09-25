import contextlib
import json
from io import StringIO
from twisted.trial import unittest

from lbrynet.cli import normalize_value, main
from lbrynet.core.system_info import get_platform


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

        self.assertEqual(True, normalize_value('TRUE'))
        self.assertEqual(True, normalize_value('true'))
        self.assertEqual(True, normalize_value('TrUe'))
        self.assertEqual(False, normalize_value('FALSE'))
        self.assertEqual(False, normalize_value('false'))
        self.assertEqual(False, normalize_value('FaLsE'))
        self.assertEqual(True, normalize_value(True))

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
        self.assertSubstring('lbrynet - LBRY command line client.', actual_output)
        self.assertSubstring('USAGE', actual_output)

    def test_help_for_command_command(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            main(['help', 'publish'])
        actual_output = actual_output.getvalue()
        self.assertSubstring('Make a new name claim and publish', actual_output)
        self.assertSubstring('Usage:', actual_output)

    def test_help_for_command_command_with_invalid_command(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            main(['help', 'publish1'])
        self.assertSubstring('Invalid command name', actual_output.getvalue())

    def test_version_command(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            main(['version'])
        self.assertEqual(
            actual_output.getvalue().strip(),
            json.dumps(get_platform(get_ip=False), sort_keys=True, indent=2)
        )

    def test_invalid_command(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            main(['publish1'])
        self.assertEqual(
            actual_output.getvalue().strip(),
            "publish1 is not a valid command."
        )

    def test_valid_command_daemon_not_started(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            main(["publish", '--name=asd', '--bid=99'])
        self.assertEqual(
            actual_output.getvalue().strip(),
            "Could not connect to daemon. Are you sure it's running?"
        )

    def test_deprecated_command_daemon_not_started(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            main(["wallet_balance"])
        self.assertEqual(
            actual_output.getvalue().strip(),
            "wallet_balance is deprecated, using account_balance.\n"
            "Could not connect to daemon. Are you sure it's running?"
        )
