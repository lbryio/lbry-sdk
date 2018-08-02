import contextlib
import json
from io import StringIO
from twisted.trial import unittest

from lbrynet.core.system_info import get_platform
from lbrynet import cli


class CLITest(unittest.TestCase):
    def test_guess_type(self):
        self.assertEqual('0.3.8', cli.guess_type('0.3.8'))
        self.assertEqual(0.3, cli.guess_type('0.3'))
        self.assertEqual(3, cli.guess_type('3'))

        self.assertEqual('VdNmakxFORPSyfCprAD/eDDPk5TY9QYtSA==',
                         cli.guess_type('VdNmakxFORPSyfCprAD/eDDPk5TY9QYtSA=='))

        self.assertEqual(True, cli.guess_type('TRUE'))
        self.assertEqual(True, cli.guess_type('true'))
        self.assertEqual(True, cli.guess_type('TrUe'))
        self.assertEqual(False, cli.guess_type('FALSE'))
        self.assertEqual(False, cli.guess_type('false'))
        self.assertEqual(False, cli.guess_type('FaLsE'))

        self.assertEqual('3', cli.guess_type('3', key="uri"))
        self.assertEqual('0.3', cli.guess_type('0.3', key="uri"))
        self.assertEqual('True', cli.guess_type('True', key="uri"))
        self.assertEqual('False', cli.guess_type('False', key="uri"))

        self.assertEqual('3', cli.guess_type('3', key="file_name"))
        self.assertEqual('3', cli.guess_type('3', key="name"))
        self.assertEqual('3', cli.guess_type('3', key="download_directory"))
        self.assertEqual('3', cli.guess_type('3', key="channel_name"))

        self.assertEqual(3, cli.guess_type('3', key="some_other_thing"))

        self.assertEqual(3, cli.guess_type(3))
        self.assertEqual(True, cli.guess_type(True))

    def test_help_c0mmand(self):
        expected_output = StringIO()
        with contextlib.redirect_stdout(expected_output):
            cli.print_help()
        expected_output = expected_output.getvalue().strip()

        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            cli.main(['help'])
        actual_output = actual_output.getvalue().strip()

        self.assertEqual(expected_output, actual_output)

    def test_help_for_command_command(self):
        # testing only publish command

        expected_output = StringIO()
        with contextlib.redirect_stdout(expected_output):
            cli.print_help_for_command("publish")
        expected_output = expected_output.getvalue().strip()

        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            cli.main(['help', 'publish'])
        actual_output = actual_output.getvalue().strip()

        self.assertEqual(expected_output, actual_output)

    def test_help_for_command_command_with_invalid_command(self):
        expected_output = StringIO()
        with contextlib.redirect_stdout(expected_output):
            cli.print_help_for_command("publish1")
        expected_output = expected_output.getvalue().strip()

        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            cli.main(['help', 'publish1'])
        actual_output = actual_output.getvalue().strip()

        self.assertEqual(expected_output, actual_output)

    def test_version_command(self):
        expected_output = json.dumps(get_platform(get_ip=False), sort_keys=True, indent=2, separators=(',', ': '))
        expected_output = expected_output.strip()

        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            cli.main(['version'])
        actual_output = actual_output.getvalue().strip()

        self.assertEqual(expected_output, actual_output)

    def test_invalid_command(self):
        invalid_command = "publish1"
        expected_output = "{} is not a valid command.".format(invalid_command)

        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            cli.main([invalid_command])
        actual_output = actual_output.getvalue().strip()

        self.assertEqual(expected_output, actual_output)

    def test_valid_command_daemon_not_started(self):
        valid_command = "publish"
        expected_output = "Could not connect to daemon. Are you sure it's running?"

        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            cli.main([valid_command, '--name=asd', '--bid=99'])
        actual_output = actual_output.getvalue().strip()

        self.assertEqual(expected_output, actual_output)
