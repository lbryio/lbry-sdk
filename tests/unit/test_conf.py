import os
import json
import sys
import types
import tempfile
import shutil
import unittest
import argparse
from lbrynet import conf
from lbrynet.p2p.Error import InvalidCurrencyError


class TestConfig(conf.Configuration):
    test = conf.String('the default')
    test_int = conf.Integer(9)
    test_toggle = conf.Toggle(False)
    servers = conf.Servers([('localhost', 80)])


class ConfigurationTests(unittest.TestCase):

    @unittest.skipIf('linux' not in sys.platform, 'skipping linux only test')
    def test_linux_defaults(self):
        c = TestConfig()
        self.assertEqual(c.data_dir, os.path.expanduser('~/.local/share/lbry/lbrynet'))
        self.assertEqual(c.wallet_dir, os.path.expanduser('~/.local/share/lbry/lbryum'))
        self.assertEqual(c.download_dir, os.path.expanduser('~/Downloads'))
        self.assertEqual(c.config, os.path.expanduser('~/.local/share/lbry/lbrynet/daemon_settings.yml'))

    def test_search_order(self):
        c = TestConfig()
        c.runtime = {'test': 'runtime'}
        c.arguments = {'test': 'arguments'}
        c.environment = {'test': 'environment'}
        c.persisted = {'test': 'persisted'}
        self.assertEqual(c.test, 'runtime')
        c.runtime = {}
        self.assertEqual(c.test, 'arguments')
        c.arguments = {}
        self.assertEqual(c.test, 'environment')
        c.environment = {}
        self.assertEqual(c.test, 'persisted')
        c.persisted = {}
        self.assertEqual(c.test, 'the default')

    def test_arguments(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--test")
        args = parser.parse_args(['--test', 'blah'])
        c = TestConfig.create_from_arguments(args)
        self.assertEqual(c.test, 'blah')
        c.arguments = {}
        self.assertEqual(c.test, 'the default')

    def test_environment(self):
        c = TestConfig()
        self.assertEqual(c.test, 'the default')
        c.set_environment({'LBRY_TEST': 'from environ'})
        self.assertEqual(c.test, 'from environ')

    def test_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:

            c = TestConfig.create_from_arguments(
                types.SimpleNamespace(config=os.path.join(temp_dir, 'settings.yml'))
            )

            # settings.yml doesn't exist on file system
            self.assertFalse(c.persisted.exists)
            self.assertEqual(c.test, 'the default')

            self.assertEqual(c.modify_order, [c.runtime])
            with c.update_config():
                self.assertEqual(c.modify_order, [c.runtime, c.persisted])
                c.test = 'new value'
            self.assertEqual(c.modify_order, [c.runtime])

            # share_usage_data has been saved to settings file
            self.assertTrue(c.persisted.exists)
            with open(c.config, 'r') as fd:
                self.assertEqual(fd.read(), 'test: new value\n')

            # load the settings file and check share_usage_data is false
            c = TestConfig.create_from_arguments(
                types.SimpleNamespace(config=os.path.join(temp_dir, 'settings.yml'))
            )
            self.assertTrue(c.persisted.exists)
            self.assertEqual(c.test, 'new value')

            # setting in runtime overrides config
            self.assertNotIn('test', c.runtime)
            c.test = 'from runtime'
            self.assertIn('test', c.runtime)
            self.assertEqual(c.test, 'from runtime')

            # NOT_SET only clears it in runtime location
            c.test = conf.NOT_SET
            self.assertNotIn('test', c.runtime)
            self.assertEqual(c.test, 'new value')

            # clear it in persisted as well
            self.assertIn('test', c.persisted)
            with c.update_config():
                c.test = conf.NOT_SET
            self.assertNotIn('test', c.persisted)
            self.assertEqual(c.test, 'the default')
            with open(c.config, 'r') as fd:
                self.assertEqual(fd.read(), '{}\n')

    def test_validation(self):
        c = TestConfig()
        with self.assertRaisesRegex(AssertionError, 'must be a string'):
            c.test = 9
        with self.assertRaisesRegex(AssertionError, 'must be an integer'):
            c.test_int = 'hi'
        with self.assertRaisesRegex(AssertionError, 'must be a true/false'):
            c.test_toggle = 'hi'

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

    def test_max_key_fee(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = os.path.join(temp_dir, 'settings.yml')
            with open(config, 'w') as fd:
                fd.write('max_key_fee: \'{"currency":"USD", "amount":1}\'\n')
            c = conf.ServerConfiguration.create_from_arguments(
                types.SimpleNamespace(config=config)
            )
            self.assertEqual(c.max_key_fee['currency'], 'USD')
            self.assertEqual(c.max_key_fee['amount'], 1)
            with self.assertRaises(InvalidCurrencyError):
                c.max_key_fee = {'currency': 'BCH', 'amount': 1}
            with c.update_config():
                c.max_key_fee = {'currency': 'BTC', 'amount': 1}
            with open(config, 'r') as fd:
                self.assertEqual(fd.read(), 'max_key_fee: \'{"currency": "BTC", "amount": 1}\'\n')
