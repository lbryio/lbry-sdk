from twisted.internet.task import Clock
from twisted.trial import unittest

from lbrynet.daemon.ComponentManager import ComponentManager
from lbrynet.daemon import Components
from lbrynet.tests import mocks


class TestComponentManager(unittest.TestCase):
    def setUp(self):
        mocks.mock_conf_settings(self)
        self.default_components_sort = [
            [Components.DatabaseComponent,
             Components.UPnPComponent],
            [Components.DHTComponent,
             Components.WalletComponent],
            [Components.HashAnnouncer],
            [Components.SessionComponent],
            [Components.PeerProtocolServer,
             Components.StreamIdentifier],
            [Components.FileManager],
            [Components.ReflectorComponent]
        ]
        self.component_manager = ComponentManager()

    def tearDown(self):
        pass

    def test_sort_components(self):
        stages = self.component_manager.sort_components()

        for stage_list, sorted_stage_list in zip(stages, self.default_components_sort):
            self.assertSetEqual(set([type(stage) for stage in stage_list]), set(sorted_stage_list))

    def test_sort_components_reverse(self):
        rev_stages = self.component_manager.sort_components(reverse=True)
        reverse_default_components_sort = reversed(self.default_components_sort)

        for stage_list, sorted_stage_list in zip(rev_stages, reverse_default_components_sort):
            self.assertSetEqual(set([type(stage) for stage in stage_list]), set(sorted_stage_list))

    def test_get_component_not_exists(self):

        with self.assertRaises(NameError):
            self.component_manager.get_component("random_component")


class TestComponentManagerOverrides(unittest.TestCase):
    def setUp(self):
        mocks.mock_conf_settings(self)

    def test_init_with_overrides(self):
        class FakeWallet(object):
            component_name = "wallet"
            depends_on = []

            def __init__(self, component_manager):
                self.component_manager = component_manager

            @property
            def component(self):
                return self

        new_component_manager = ComponentManager(wallet=FakeWallet)
        fake_wallet = new_component_manager.get_component("wallet")
        # wallet should be an instance of FakeWallet and not WalletComponent from Components.py
        self.assertEquals(type(fake_wallet), FakeWallet)
        self.assertNotEquals(type(fake_wallet), Components.WalletComponent)

    def test_init_with_wrong_overrides(self):
        class FakeRandomComponent(object):
            component_name = "someComponent"
            depends_on = []

        with self.assertRaises(SyntaxError):
            ComponentManager(randomComponent=FakeRandomComponent)


class TestComponentManagerProperStart(unittest.TestCase):
    def setUp(self):
        self.reactor = Clock()
        mocks.mock_conf_settings(self)
        self.component_manager = ComponentManager(
            skip_components=["database", "dht", "hashAnnouncer", "streamIdentifier",
                             "peerProtocolServer", "reflector", "upnp"],
            reactor=self.reactor,
            wallet=mocks.FakeDelayedWallet,
            session=mocks.FakeDelayedSession,
            fileManager=mocks.FakeDelayedFileManager
        )

    def tearDown(self):
        pass

    def test_proper_starting_of_components(self):
        self.component_manager.setup()
        self.assertTrue(self.component_manager.get_component('wallet').running)
        self.assertFalse(self.component_manager.get_component('session').running)
        self.assertFalse(self.component_manager.get_component('file_manager').running)

        self.reactor.advance(1)
        self.assertTrue(self.component_manager.get_component('wallet').running)
        self.assertTrue(self.component_manager.get_component('session').running)
        self.assertFalse(self.component_manager.get_component('file_manager').running)

        self.reactor.advance(1)
        self.assertTrue(self.component_manager.get_component('wallet').running)
        self.assertTrue(self.component_manager.get_component('session').running)
        self.assertTrue(self.component_manager.get_component('file_manager').running)

    def test_proper_stopping_of_components(self):
        self.component_manager.setup()
        self.reactor.advance(1)
        self.reactor.advance(1)
        self.component_manager.stop()
        self.assertFalse(self.component_manager.get_component('file_manager').running)
        self.assertTrue(self.component_manager.get_component('session').running)
        self.assertTrue(self.component_manager.get_component('wallet').running)

        self.reactor.advance(1)
        self.assertFalse(self.component_manager.get_component('file_manager').running)
        self.assertFalse(self.component_manager.get_component('session').running)
        self.assertTrue(self.component_manager.get_component('wallet').running)

        self.reactor.advance(1)
        self.assertFalse(self.component_manager.get_component('file_manager').running)
        self.assertFalse(self.component_manager.get_component('session').running)
        self.assertFalse(self.component_manager.get_component('wallet').running)
