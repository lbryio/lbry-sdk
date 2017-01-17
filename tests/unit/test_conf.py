import os

from twisted.trial import unittest

from lbrynet import conf


class SettingsTest(unittest.TestCase):
    def setUp(self):
        os.environ['LBRY_TEST'] = 'test_string'

    def tearDown(self):
        del os.environ['LBRY_TEST']

    @staticmethod
    def get_mock_config_instance():
        env = conf.Env(test=(str, ''))
        return conf.Config({}, {'test': (str, '')}, environment=env)

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
