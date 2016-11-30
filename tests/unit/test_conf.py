import os

from twisted.trial import unittest

from lbrynet import conf


class SettingsTest(unittest.TestCase):
    def setUp(self):
        os.environ['LBRY_TEST'] = 'test_string'

    def tearDown(self):
        del os.environ['LBRY_TEST']

    def test_envvar_is_read(self):
        env = conf.Env(test=(str, ''))
        settings = conf.AdjustableSettings(env)
        self.assertEqual('test_string', settings.test)

    def test_setting_can_be_overriden(self):
        env = conf.Env(test=(str, ''))
        settings = conf.AdjustableSettings(env)
        settings.test = 'my_override'
        self.assertEqual('my_override', settings.test)

    def test_setting_can_be_updated(self):
        env = conf.Env(test=(str, ''))
        settings = conf.AdjustableSettings(env)
        settings.update({'test': 'my_update'})
        self.assertEqual('my_update', settings.test)

    def test_setting_is_in_dict(self):
        env = conf.Env(test=(str, ''))
        settings = conf.AdjustableSettings(env)
        setting_dict = settings.get_dict()
        self.assertEqual({'test': 'test_string'}, setting_dict)
