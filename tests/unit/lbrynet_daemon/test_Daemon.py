import mock
import requests
from twisted.trial import unittest

from lbrynet.lbrynet_daemon import Daemon


class MiscTests(unittest.TestCase):
    def test_get_lbrynet_version_from_github(self):
        response = mock.create_autospec(requests.Response)
        # don't need to mock out the entire response from the api
        # but at least need 'tag_name'
        response.json.return_value = {
            "url": "https://api.github.com/repos/lbryio/lbry/releases/3685199",
            "assets_url": "https://api.github.com/repos/lbryio/lbry/releases/3685199/assets",
            "html_url": "https://github.com/lbryio/lbry/releases/tag/v0.3.8",
            "id": 3685199,
            "tag_name": "v0.3.8",
            "prerelease": False
        }
        with mock.patch('lbrynet.lbrynet_daemon.Daemon.requests') as req:
            req.get.return_value = response
            self.assertEqual('0.3.8', Daemon.get_lbrynet_version_from_github())

    def test_error_is_thrown_if_prerelease(self):
        response = mock.create_autospec(requests.Response)
        response.json.return_value = {
            "tag_name": "v0.3.8",
            "prerelease": True
        }
        with mock.patch('lbrynet.lbrynet_daemon.Daemon.requests') as req:
            req.get.return_value = response
            with self.assertRaises(Exception):
                Daemon.get_lbrynet_version_from_github()

    def test_error_is_thrown_when_version_cant_be_parsed(self):
        with self.assertRaises(Exception):
            Daemon.get_version_from_tag('garbage')
