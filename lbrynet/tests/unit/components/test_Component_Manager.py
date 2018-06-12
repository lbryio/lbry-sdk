from twisted.internet import defer, reactor
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

    def tearDown(self):
        pass

    def test_sort_components(self):
        component_manager = ComponentManager()
        stages = component_manager.sort_components()

        for stage_list, sorted_stage_list in zip(stages, self.default_components_sort):
            for stage in stage_list:
                self.assertIsInstance(stage, tuple(sorted_stage_list))

    def test_sort_components_reverse(self):
        component_manager = ComponentManager()
        rev_stages = component_manager.sort_components(reverse=True)
        reverse_default_components_sort = reversed(self.default_components_sort)

        for stage_list, sorted_stage_list in zip(rev_stages, reverse_default_components_sort):
            for stage in stage_list:
                self.assertIsInstance(stage, tuple(sorted_stage_list))

    def test_init_with_overrides(self):
        class FakeWallet(Components.WalletComponent):
            depends_on = None

            def setup(selfs):
                pass

            def stop(self):
                pass

            def component(self):
                return None


        component_manager = ComponentManager(wallet=FakeWallet)
        # component_manager.__init__(wallet=FakeWallet)
