import os
import sys
import types
import tempfile
import unittest
import argparse
import lbry.wallet
from lbry.conf import Config, BaseConfig, String, Integer, Toggle, Servers, Strings, StringChoice, NOT_SET
from lbry.error import InvalidCurrencyError


class TestConfig(BaseConfig):
    test_str = String('str help', 'the default', previous_names=['old_str'])
    test_int = Integer('int help', 9)
    test_false_toggle = Toggle('toggle help', False)
    test_true_toggle = Toggle('toggle help', True)
    servers = Servers('servers help', [('localhost', 80)])
    strings = Strings('cheese', ['string'])
    string_choice = StringChoice("one of string", ["a", "b", "c"], "a")


class ConfigurationTests(unittest.TestCase):

    @unittest.skipIf('linux' not in sys.platform, 'skipping linux only test')
    def test_linux_defaults(self):
        c = Config()
        self.assertEqual(c.data_dir, os.path.expanduser('~/.local/share/lbry/lbrynet'))
        self.assertEqual(c.wallet_dir, os.path.expanduser('~/.local/share/lbry/lbryum'))
        self.assertEqual(c.download_dir, os.path.expanduser('~/Downloads'))
        self.assertEqual(c.config, os.path.expanduser('~/.local/share/lbry/lbrynet/daemon_settings.yml'))
        self.assertEqual(c.api_connection_url, 'http://localhost:5279/lbryapi')
        self.assertEqual(c.log_file_path, os.path.expanduser('~/.local/share/lbry/lbrynet/lbrynet.log'))

    def test_search_order(self):
        c = TestConfig()
        c.runtime = {'test_str': 'runtime'}
        c.arguments = {'test_str': 'arguments'}
        c.environment = {'test_str': 'environment'}
        c.persisted = {'test_str': 'persisted'}
        self.assertEqual(c.test_str, 'runtime')
        c.runtime = {}
        self.assertEqual(c.test_str, 'arguments')
        c.arguments = {}
        self.assertEqual(c.test_str, 'environment')
        c.environment = {}
        self.assertEqual(c.test_str, 'persisted')
        c.persisted = {}
        self.assertEqual(c.test_str, 'the default')

    def test_arguments(self):
        parser = argparse.ArgumentParser()
        TestConfig.contribute_to_argparse(parser)

        args = parser.parse_args([])
        c = TestConfig.create_from_arguments(args)
        self.assertEqual(c.test_str, 'the default')
        self.assertTrue(c.test_true_toggle)
        self.assertFalse(c.test_false_toggle)
        self.assertEqual(c.servers, [('localhost', 80)])
        self.assertEqual(c.strings, ['string'])

        args = parser.parse_args(['--test-str', 'blah'])
        c = TestConfig.create_from_arguments(args)
        self.assertEqual(c.test_str, 'blah')
        self.assertTrue(c.test_true_toggle)
        self.assertFalse(c.test_false_toggle)

        args = parser.parse_args(['--test-true-toggle'])
        c = TestConfig.create_from_arguments(args)
        self.assertTrue(c.test_true_toggle)
        self.assertFalse(c.test_false_toggle)

        args = parser.parse_args(['--test-false-toggle'])
        c = TestConfig.create_from_arguments(args)
        self.assertTrue(c.test_true_toggle)
        self.assertTrue(c.test_false_toggle)

        args = parser.parse_args(['--no-test-true-toggle'])
        c = TestConfig.create_from_arguments(args)
        self.assertFalse(c.test_true_toggle)
        self.assertFalse(c.test_false_toggle)

        args = parser.parse_args(['--servers=localhost:1', '--servers=192.168.0.1:2'])
        c = TestConfig.create_from_arguments(args)
        self.assertEqual(c.servers, [('localhost', 1), ('192.168.0.1', 2)])

        args = parser.parse_args(['--strings=cheddar', '--strings=mozzarella'])
        c = TestConfig.create_from_arguments(args)
        self.assertEqual(c.strings, ['cheddar', 'mozzarella'])

    def test_environment(self):
        c = TestConfig()

        self.assertEqual(c.test_str, 'the default')
        c.set_environment({'LBRY_TEST_STR': 'from environ'})
        self.assertEqual(c.test_str, 'from environ')

        self.assertEqual(c.test_int, 9)
        c.set_environment({'LBRY_TEST_INT': '1'})
        self.assertEqual(c.test_int, 1)

    def test_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:

            c = TestConfig.create_from_arguments(
                types.SimpleNamespace(config=os.path.join(temp_dir, 'settings.yml'))
            )

            # settings.yml doesn't exist on file system
            self.assertFalse(c.persisted.exists)
            self.assertEqual(c.test_str, 'the default')

            self.assertEqual(c.modify_order, [c.runtime])
            with c.update_config():
                self.assertEqual(c.modify_order, [c.runtime, c.persisted])
                c.test_str = 'original'
            self.assertEqual(c.modify_order, [c.runtime])

            # share_usage_data has been saved to settings file
            self.assertTrue(c.persisted.exists)
            with open(c.config, 'r') as fd:
                self.assertEqual(fd.read(), 'test_str: original\n')

            # load the settings file and check share_usage_data is false
            c = TestConfig.create_from_arguments(
                types.SimpleNamespace(config=os.path.join(temp_dir, 'settings.yml'))
            )
            self.assertTrue(c.persisted.exists)
            self.assertEqual(c.test_str, 'original')

            # setting in runtime overrides config
            self.assertNotIn('test_str', c.runtime)
            c.test_str = 'from runtime'
            self.assertIn('test_str', c.runtime)
            self.assertEqual(c.test_str, 'from runtime')

            # without context manager NOT_SET only clears it in runtime location
            c.test_str = NOT_SET
            self.assertNotIn('test_str', c.runtime)
            self.assertEqual(c.test_str, 'original')

            # clear it in persisted as well by using context manager
            self.assertIn('test_str', c.persisted)
            with c.update_config():
                c.test_str = NOT_SET
            self.assertNotIn('test_str', c.persisted)
            self.assertEqual(c.test_str, 'the default')
            with open(c.config, 'r') as fd:
                self.assertEqual(fd.read(), '{}\n')

    def test_persisted_upgrade(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = os.path.join(temp_dir, 'settings.yml')
            with open(config, 'w') as fd:
                fd.write('old_str: old stuff\n')
            c = TestConfig.create_from_arguments(
                types.SimpleNamespace(config=config)
            )
            self.assertEqual(c.test_str, 'old stuff')
            self.assertNotIn('old_str', c.persisted)
            with open(config, 'w') as fd:
                fd.write('test_str: old stuff\n')

    def test_validation(self):
        c = TestConfig()
        with self.assertRaisesRegex(AssertionError, 'must be a string'):
            c.test_str = 9
        with self.assertRaisesRegex(AssertionError, 'must be an integer'):
            c.test_int = 'hi'
        with self.assertRaisesRegex(AssertionError, 'must be a true/false'):
            c.test_true_toggle = 'hi'
            c.test_false_toggle = 'hi'

    def test_file_extension_validation(self):
        with self.assertRaisesRegex(AssertionError, "'.json' is not supported"):
            TestConfig.create_from_arguments(
                types.SimpleNamespace(config=os.path.join('settings.json'))
            )

    def test_serialize_deserialize(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            c = TestConfig.create_from_arguments(
                types.SimpleNamespace(config=os.path.join(temp_dir, 'settings.yml'))
            )
            self.assertEqual(c.servers, [('localhost', 80)])
            with c.update_config():
                c.servers = [('localhost', 8080)]
            with open(c.config, 'r+') as fd:
                self.assertEqual(fd.read(), 'servers:\n- localhost:8080\n')
                fd.write('servers:\n  - localhost:5566\n')
            c = TestConfig.create_from_arguments(
                types.SimpleNamespace(config=os.path.join(temp_dir, 'settings.yml'))
            )
            self.assertEqual(c.servers, [('localhost', 5566)])

    def test_max_key_fee_from_yaml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = os.path.join(temp_dir, 'settings.yml')
            with open(config, 'w') as fd:
                fd.write('max_key_fee: {currency: USD, amount: 1}\n')
            c = Config.create_from_arguments(
                types.SimpleNamespace(config=config)
            )
            self.assertEqual(c.max_key_fee['currency'], 'USD')
            self.assertEqual(c.max_key_fee['amount'], 1)
            with self.assertRaises(InvalidCurrencyError):
                c.max_key_fee = {'currency': 'BCH', 'amount': 1}
            with c.update_config():
                c.max_key_fee = {'currency': 'BTC', 'amount': 1}
            with open(config, 'r') as fd:
                self.assertEqual(fd.read(), 'max_key_fee:\n  amount: 1\n  currency: BTC\n')
            with c.update_config():
                c.max_key_fee = None
            with open(config, 'r') as fd:
                self.assertEqual(fd.read(), 'max_key_fee: null\n')

    def test_max_key_fee_from_args(self):
        parser = argparse.ArgumentParser()
        Config.contribute_to_argparse(parser)

        # default
        args = parser.parse_args([])
        c = Config.create_from_arguments(args)
        self.assertEqual(c.max_key_fee, {'amount': 50.0, 'currency': 'USD'})

        # disabled
        args = parser.parse_args(['--no-max-key-fee'])
        c = Config.create_from_arguments(args)
        self.assertIsNone(c.max_key_fee)

        args = parser.parse_args(['--max-key-fee', 'null'])
        c = Config.create_from_arguments(args)
        self.assertIsNone(c.max_key_fee)

        # set
        args = parser.parse_args(['--max-key-fee', '1.0', 'BTC'])
        c = Config.create_from_arguments(args)
        self.assertEqual(c.max_key_fee, {'amount': 1.0, 'currency': 'BTC'})

    def test_string_choice(self):
        with self.assertRaisesRegex(ValueError, "No valid values provided"):
            StringChoice("no valid values", [], "")
        with self.assertRaisesRegex(ValueError, "Default value must be one of"):
            StringChoice("invalid default", ["a"], "b")

        c = TestConfig()
        self.assertEqual("a", c.string_choice)  # default
        c.string_choice = "b"
        self.assertEqual("b", c.string_choice)
        with self.assertRaisesRegex(ValueError, "Setting 'string_choice' value must be one of"):
            c.string_choice = "d"

        parser = argparse.ArgumentParser()
        TestConfig.contribute_to_argparse(parser)
        args = parser.parse_args(['--string-choice', 'c'])
        c = TestConfig.create_from_arguments(args)
        self.assertEqual("c", c.string_choice)

    def test_known_hubs_list(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            c1 = Config(config=os.path.join(temp_dir, 'settings.yml'), wallet_dir=temp_dir)
            self.assertEqual(list(c1.known_hubs), [])
            c1.known_hubs.append('new.hub.io')
            c1.known_hubs.save()
            c2 = Config(config=os.path.join(temp_dir, 'settings.yml'), wallet_dir=temp_dir)
            self.assertEqual(list(c2.known_hubs), ['new.hub.io'])
