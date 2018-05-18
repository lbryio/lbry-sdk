import os
import json

from twisted.trial import unittest
from lbrynet import conf
from lbrynet.core.Error import InvalidCurrencyError

class SettingsTest(unittest.TestCase):
    def setUp(self):
        os.environ['LBRY_TEST'] = 'test_string'

    def tearDown(self):
        del os.environ['LBRY_TEST']

    @staticmethod
    def get_mock_config_instance():
        settings = {'test': (str, '')}
        env = conf.Env(**settings)
        return conf.Config({}, settings, environment=env)

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
        self.assertEqual(str, type(conf.default_download_dir))
        self.assertEqual(str, type(conf.default_data_dir))
        self.assertEqual(str, type(conf.default_lbryum_dir))

    def test_conversion_reversal(self):
        # simulate decoding, conversion, conversion reversal and encoding of
        # server list settings from the config file.
        settings = self.get_mock_config_instance()
        encoder = conf.settings_encoders['.yml']
        decoder = conf.settings_decoders['.yml']
        conf_file_entry = "lbryum_servers: ['localhost:5001', 'localhost:5002']"
        decoded = decoder(conf_file_entry)
        converted = settings._convert_conf_file_lists(decoded)
        converted_reversed = settings._convert_conf_file_lists_reverse(converted)
        encoded = encoder(converted_reversed)
        self.assertEqual(conf_file_entry, encoded.strip())
        self.assertEqual(decoded, converted_reversed)

