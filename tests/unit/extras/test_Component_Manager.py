import asyncio
from unittest import TestCase
from torba.testcase import AdvanceTimeTestCase

from lbrynet.extras.daemon.ComponentManager import ComponentManager
from lbrynet.extras.daemon.Components import DATABASE_COMPONENT, DHT_COMPONENT
from lbrynet.extras.daemon.Components import HASH_ANNOUNCER_COMPONENT, REFLECTOR_COMPONENT, UPNP_COMPONENT
from lbrynet.extras.daemon.Components import PEER_PROTOCOL_SERVER_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
from lbrynet.extras.daemon.Components import RATE_LIMITER_COMPONENT, HEADERS_COMPONENT, PAYMENT_RATE_COMPONENT
from lbrynet.extras.daemon import Components
from tests import mocks


class TestComponentManager(TestCase):
    def setUp(self):
        mocks.mock_conf_settings(self)

        self.default_components_sort = [
            [
                Components.HeadersComponent,
                Components.DatabaseComponent,
                Components.ExchangeRateManagerComponent,
                Components.PaymentRateComponent,
                Components.RateLimiterComponent,
                Components.UPnPComponent
            ],
            [
                Components.BlobComponent,
                Components.DHTComponent,
                Components.WalletComponent
            ],
            [
                Components.FileManagerComponent,
                Components.HashAnnouncerComponent,
                Components.PeerProtocolServerComponent
            ],
            [
                Components.ReflectorComponent
            ]
        ]
        self.component_manager = ComponentManager()

    def tearDown(self):
        pass

    def test_sort_components(self):
        stages = self.component_manager.sort_components()
        for stage_list, sorted_stage_list in zip(stages, self.default_components_sort):
            self.assertEqual([type(stage) for stage in stage_list], sorted_stage_list)

    def test_sort_components_reverse(self):
        rev_stages = self.component_manager.sort_components(reverse=True)
        reverse_default_components_sort = reversed(self.default_components_sort)

        for stage_list, sorted_stage_list in zip(rev_stages, reverse_default_components_sort):
            self.assertEqual([type(stage) for stage in stage_list], sorted_stage_list)

    def test_get_component_not_exists(self):

        with self.assertRaises(NameError):
            self.component_manager.get_component("random_component")


class TestComponentManagerOverrides(TestCase):
    def setUp(self):
        mocks.mock_conf_settings(self)

    def test_init_with_overrides(self):
        class FakeWallet:
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
        self.assertIsInstance(fake_wallet, FakeWallet)
        self.assertNotIsInstance(fake_wallet, Components.WalletComponent)

    def test_init_with_wrong_overrides(self):
        class FakeRandomComponent:
            component_name = "someComponent"
            depends_on = []

        with self.assertRaises(SyntaxError):
            ComponentManager(randomComponent=FakeRandomComponent)


class TestComponentManagerProperStart(AdvanceTimeTestCase):

    def setUp(self):
        mocks.mock_conf_settings(self)
        self.component_manager = ComponentManager(
            skip_components=[DATABASE_COMPONENT, DHT_COMPONENT, HASH_ANNOUNCER_COMPONENT,
                             PEER_PROTOCOL_SERVER_COMPONENT, REFLECTOR_COMPONENT, UPNP_COMPONENT,
                             HEADERS_COMPONENT, PAYMENT_RATE_COMPONENT, RATE_LIMITER_COMPONENT,
                             EXCHANGE_RATE_MANAGER_COMPONENT],
            wallet=mocks.FakeDelayedWallet,
            file_manager=mocks.FakeDelayedFileManager,
            blob_manager=mocks.FakeDelayedBlobManager
        )

    async def test_proper_starting_of_components(self):
        asyncio.create_task(self.component_manager.setup())

        await self.advance(0)
        self.assertTrue(self.component_manager.get_component('wallet').running)
        self.assertFalse(self.component_manager.get_component('blob_manager').running)
        self.assertFalse(self.component_manager.get_component('file_manager').running)

        await self.advance(1)
        self.assertTrue(self.component_manager.get_component('wallet').running)
        self.assertTrue(self.component_manager.get_component('blob_manager').running)
        self.assertFalse(self.component_manager.get_component('file_manager').running)

        await self.advance(1)
        self.assertTrue(self.component_manager.get_component('wallet').running)
        self.assertTrue(self.component_manager.get_component('blob_manager').running)
        self.assertTrue(self.component_manager.get_component('file_manager').running)

    async def test_proper_stopping_of_components(self):
        asyncio.create_task(self.component_manager.setup())
        await self.advance(0)
        await self.advance(1)
        await self.advance(1)
        self.assertTrue(self.component_manager.get_component('wallet').running)
        self.assertTrue(self.component_manager.get_component('blob_manager').running)
        self.assertTrue(self.component_manager.get_component('file_manager').running)

        asyncio.create_task(self.component_manager.stop())
        await self.advance(0)
        self.assertFalse(self.component_manager.get_component('file_manager').running)
        self.assertTrue(self.component_manager.get_component('blob_manager').running)
        self.assertTrue(self.component_manager.get_component('wallet').running)
        await self.advance(1)
        self.assertFalse(self.component_manager.get_component('file_manager').running)
        self.assertFalse(self.component_manager.get_component('blob_manager').running)
        self.assertTrue(self.component_manager.get_component('wallet').running)
        await self.advance(1)
        self.assertFalse(self.component_manager.get_component('file_manager').running)
        self.assertFalse(self.component_manager.get_component('blob_manager').running)
        self.assertFalse(self.component_manager.get_component('wallet').running)
