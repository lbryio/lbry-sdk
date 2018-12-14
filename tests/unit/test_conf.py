import os
import json
import sys
import tempfile
import shutil
from unittest import skipIf
from twisted.trial import unittest
from twisted.internet import defer
from lbrynet import conf
from lbrynet.p2p.Error import InvalidCurrencyError


class SettingsTest(unittest.TestCase):
    def setUp(self):
        os.environ['LBRY_TEST'] = 'test_string'

    def tearDown(self):
        del os.environ['LBRY_TEST']

    def get_mock_config_instance(self):
        settings = {'test': (str, '')}
        env = conf.Env(**settings)
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda : defer.succeed(shutil.rmtree(self.tmp_dir)))
        return conf.Config({}, settings, environment=env, data_dir=self.tmp_dir, wallet_dir=self.tmp_dir, download_dir=self.tmp_dir)

    def test_envvar_is_read(self):
        settings = self.get_mock_config_instance()
        self.assertEqual('test_string', settings['test'])

    def test_setting_can_be_overridden(self):
        settings = self.get_mock_config_instance()
        settings['test'] = 'my_override'
        self.assertEqual('my_override', settings['test'])

    def test_setting_can_be_updated(self):
        settings = self.get_mock_config_instance()
        settings.update({'test': 'my_update'})
        self.assertEqual('my_update', settings['test'])

    def test_setting_is_in_dict(self):
        settings = self.get_mock_config_instance()
        setting_dict = settings.get_current_settings_dict()
        self.assertEqual({'test': 'test_string'}, setting_dict)

    def test_invalid_setting_raises_exception(self):
        settings = self.get_mock_config_instance()
        self.assertRaises(KeyError, settings.set, 'invalid_name', 123)

    def test_invalid_data_type_raises_exception(self):
        settings = self.get_mock_config_instance()
        self.assertIsNone(settings.set('test', 123))
        self.assertRaises(KeyError, settings.set, 'test', 123, ('fake_data_type',))

    def test_setting_precedence(self):
        settings = self.get_mock_config_instance()
        settings.set('test', 'cli_test_string', data_types=(conf.TYPE_CLI,))
        self.assertEqual('cli_test_string', settings['test'])
        settings.set('test', 'this_should_not_take_precedence', data_types=(conf.TYPE_ENV,))
        self.assertEqual('cli_test_string', settings['test'])
        settings.set('test', 'runtime_takes_precedence', data_types=(conf.TYPE_RUNTIME,))
        self.assertEqual('runtime_takes_precedence', settings['test'])

    def test_max_key_fee_set(self):
        fixed_default = {'CURRENCIES':{'BTC':{'type':'crypto'}}}
        adjustable_settings = {'max_key_fee': (json.loads, {'currency':'USD', 'amount':1})}
        env = conf.Env(**adjustable_settings)
        settings = conf.Config(fixed_default, adjustable_settings, environment=env)

        with self.assertRaises(InvalidCurrencyError):
            settings.set('max_key_fee', {'currency':'USD', 'amount':1})

        valid_setting = {'currency':'BTC', 'amount':1}
        settings.set('max_key_fee', valid_setting)
        out = settings.get('max_key_fee')
        self.assertEqual(out, valid_setting)

    def test_data_dir(self):
        # check if these directories are returned as string and not unicode
        # otherwise there will be problems when calling os.path.join on
        # unicode directory names with string file names
        settings = conf.Config({}, {})
        self.assertEqual(str, type(settings.download_dir))
        self.assertEqual(str, type(settings.data_dir))
        self.assertEqual(str, type(settings.wallet_dir))

    @skipIf('win' in sys.platform, 'fix me!')
    def test_load_save_config_file(self):
        # setup settings
        adjustable_settings = {'lbryum_servers': (list, [])}
        env = conf.Env(**adjustable_settings)
        settings = conf.Config({}, adjustable_settings, environment=env)
        conf.settings = settings
        # setup tempfile
        conf_entry = b"lbryum_servers: ['localhost:50001', 'localhost:50002']\n"
        with tempfile.NamedTemporaryFile(suffix='.yml') as conf_file:
            conf_file.write(conf_entry)
            conf_file.seek(0)
            conf.conf_file = conf_file.name
            # load and save settings from conf file
            settings.load_conf_file_settings()
            settings.save_conf_file_settings()
            # test if overwritten entry equals original entry
            # use decoded versions, because format might change without
            # changing the interpretation
            decoder = conf.settings_decoders['.yml']
            conf_decoded = decoder(conf_entry)
            conf_entry_new = conf_file.read()
            conf_decoded_new = decoder(conf_entry_new)
            self.assertEqual(conf_decoded, conf_decoded_new)

    def test_load_file(self):
        settings = self.get_mock_config_instance()

        # invalid extensions
        for filename in ('monkey.yymmll', 'monkey'):
            settings.file_name = filename
            with open(os.path.join(self.tmp_dir, filename), "w"):
                pass
            with self.assertRaises(ValueError):
                settings.load_conf_file_settings()
