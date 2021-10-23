import os
import tempfile
import shutil
import contextlib
import logging
import pathlib
from io import StringIO
from unittest import TestCase
from unittest.mock import patch
from types import SimpleNamespace
from contextlib import asynccontextmanager

import docopt
from lbry.testcase import AsyncioTestCase

from lbry.extras.cli import normalize_value, main, setup_logging, ensure_directory_exists
from lbry.extras.system_info import get_platform
from lbry.extras.daemon.daemon import Daemon
from lbry.conf import Config
from lbry.extras import cli


@asynccontextmanager
async def get_logger(argv, **conf_options):
    # loggly requires loop, so we do this in async function

    logger = logging.getLogger('test-root-logger')
    temp_dir = tempfile.mkdtemp()
    temp_config = os.path.join(temp_dir, 'settings.yml')

    try:
        # create a config (to be loaded on startup)
        _conf = Config.create_from_arguments(SimpleNamespace(config=temp_config))
        with _conf.update_config():
            for opt_name, opt_value in conf_options.items():
                setattr(_conf, opt_name, opt_value)

        # do what happens on startup
        argv.extend(['--data-dir', temp_dir])
        argv.extend(['--wallet-dir', temp_dir])
        argv.extend(['--config', temp_config])
        parser = cli.get_argument_parser()
        args, command_args = parser.parse_known_args(argv)
        conf: Config = Config.create_from_arguments(args)
        setup_logging(logger, args, conf)
        yield logger

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        for mod in cli.LOG_MODULES:
            log = logger.getChild(mod)
            log.setLevel(logging.NOTSET)
            while log.handlers:
                h = log.handlers[0]
                log.removeHandler(log.handlers[0])
                h.close()


class CLILoggingTest(AsyncioTestCase):

    async def test_verbose_logging(self):
        async with get_logger(["start", "--quiet"], share_usage_data=False) as log:
            log = log.getChild("lbry")
            self.assertTrue(log.isEnabledFor(logging.INFO))
            self.assertFalse(log.isEnabledFor(logging.DEBUG))
            self.assertEqual(len(log.handlers), 1)
            self.assertIsInstance(log.handlers[0], logging.handlers.RotatingFileHandler)

        async with get_logger(["start", "--verbose"]) as log:
            self.assertTrue(log.getChild("lbry").isEnabledFor(logging.DEBUG))
            self.assertTrue(log.getChild("lbry").isEnabledFor(logging.INFO))
            self.assertFalse(log.getChild("torba").isEnabledFor(logging.DEBUG))

        async with get_logger(["start", "--verbose", "lbry.extras", "lbry.wallet", "torba.client"]) as log:
            self.assertTrue(log.getChild("lbry.extras").isEnabledFor(logging.DEBUG))
            self.assertTrue(log.getChild("lbry.wallet").isEnabledFor(logging.DEBUG))
            self.assertTrue(log.getChild("torba.client").isEnabledFor(logging.DEBUG))
            self.assertFalse(log.getChild("lbry").isEnabledFor(logging.DEBUG))
            self.assertFalse(log.getChild("torba").isEnabledFor(logging.DEBUG))

    async def test_quiet(self):
        async with get_logger(["start"]) as log:  # default is loud
            log = log.getChild("lbry")
            self.assertEqual(len(log.handlers), 2)
            self.assertIs(type(log.handlers[1]), logging.StreamHandler)
        async with get_logger(["start", "--quiet"]) as log:
            log = log.getChild("lbry")
            self.assertEqual(len(log.handlers), 1)
            self.assertIsNot(type(log.handlers[0]), logging.StreamHandler)


class CLITest(AsyncioTestCase):

    @staticmethod
    def shell(argv):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            with contextlib.redirect_stderr(actual_output):
                try:
                    main(argv)
                except SystemExit as e:
                    print(e.args[0])
        return actual_output.getvalue().strip()

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
        self.assertEqual('3', normalize_value('3', key="claim_name"))

        self.assertEqual(3, normalize_value('3', key="some_other_thing"))

    def test_help(self):
        self.assertIn('lbrynet [-v] [--api HOST:PORT]', self.shell(['--help']))
        # start is special command, with separate help handling
        self.assertIn('--share-usage-data', self.shell(['start', '--help']))
        # publish is ungrouped command, returns usage only implicitly
        self.assertIn('publish (<name> | --name=<name>)', self.shell(['publish']))
        # publish is ungrouped command, with explicit --help
        self.assertIn('Create or replace a stream claim at a given name', self.shell(['publish', '--help']))
        # account is a group, returns help implicitly
        self.assertIn('Return the balance of an account', self.shell(['account']))
        # account is a group, with explicit --help
        self.assertIn('Return the balance of an account', self.shell(['account', '--help']))
        # account add is a grouped command, returns usage implicitly
        self.assertIn('account_add (<account_name> | --account_name=<account_name>)', self.shell(['account', 'add']))
        # account add is a grouped command, with explicit --help
        self.assertIn('Add a previously created account from a seed,', self.shell(['account', 'add', '--help']))

    def test_help_error_handling(self):
        # person tries `help` command, then they get help even though that's invalid command
        self.assertIn('--config FILE', self.shell(['help']))
        # help for invalid command, with explicit --help
        self.assertIn('--config FILE', self.shell(['nonexistant', '--help']))
        # help for invalid command, implicit
        self.assertIn('--config FILE', self.shell(['nonexistant']))

    def test_version_command(self):
        self.assertEqual(
            "lbrynet {lbrynet_version}".format(**get_platform()), self.shell(['--version'])
        )

    def test_valid_command_daemon_not_started(self):
        self.assertEqual(
            "Could not connect to daemon. Are you sure it's running?",
            self.shell(["publish", 'asd'])
        )

    def test_deprecated_command_daemon_not_started(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            main(["channel", "new", "@foo", "1.0"])
        self.assertEqual(
            actual_output.getvalue().strip(),
            "channel_new is deprecated, using channel_create.\n"
            "Could not connect to daemon. Are you sure it's running?"
        )

    @patch.object(Daemon, 'start', spec=Daemon, wraps=Daemon.start)
    def test_keyboard_interrupt_handling(self, mock_daemon_start):
        def side_effect():
            raise KeyboardInterrupt

        mock_daemon_start.side_effect = side_effect
        self.shell(["start", "--no-logging"])
        mock_daemon_start.assert_called_once()


class DaemonDocsTests(TestCase):

    def test_can_parse_api_method_docs(self):
        failures = []
        for name, fn in Daemon.callable_methods.items():
            try:
                docopt.docopt(fn.__doc__, ())
            except docopt.DocoptLanguageError as err:
                failures.append(f"invalid docstring for {name}, {err.args[0]}")
            except docopt.DocoptExit:
                pass
        if failures:
            self.fail("\n" + "\n".join(failures))


class EnsureDirectoryExistsTests(TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_when_parent_dir_does_not_exist_then_dir_is_created_with_parent(self):
        dir_path = os.path.join(self.temp_dir, "parent_dir", "dir")
        ensure_directory_exists(dir_path)
        self.assertTrue(os.path.exists(dir_path))

    def test_when_non_writable_dir_exists_then_raise(self):
        dir_path = os.path.join(self.temp_dir, "dir")
        pathlib.Path(dir_path).mkdir(mode=0o555)  # creates a non-writable, readable and executable dir
        with self.assertRaises(PermissionError):
            ensure_directory_exists(dir_path)

    def test_when_dir_exists_and_writable_then_no_raise(self):
        dir_path = os.path.join(self.temp_dir, "dir")
        pathlib.Path(dir_path).mkdir(mode=0o777)  # creates a writable, readable and executable dir
        try:
            ensure_directory_exists(dir_path)
        except (FileExistsError, PermissionError) as err:
            self.fail(f"{type(err).__name__} was raised")

    def test_when_non_dir_file_exists_at_path_then_raise(self):
        file_path = os.path.join(self.temp_dir, "file.extension")
        pathlib.Path(file_path).touch()
        with self.assertRaises(FileExistsError):
            ensure_directory_exists(file_path)
