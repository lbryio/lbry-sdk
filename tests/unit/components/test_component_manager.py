import asyncio
from lbry.testcase import AsyncioTestCase, AdvanceTimeTestCase

from lbry.conf import Config
from lbry.extras.daemon.componentmanager import ComponentManager
from lbry.extras.daemon.components import DATABASE_COMPONENT, DHT_COMPONENT
from lbry.extras.daemon.components import HASH_ANNOUNCER_COMPONENT, UPNP_COMPONENT
from lbry.extras.daemon.components import PEER_PROTOCOL_SERVER_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
from lbry.extras.daemon import components


class TestComponentManager(AsyncioTestCase):

    def setUp(self):
        self.default_components_sort = [
            [
                components.DatabaseComponent,
                components.ExchangeRateManagerComponent,
                components.UPnPComponent
            ],
            [
                components.BlobComponent,
                components.DHTComponent,
                components.WalletComponent
            ],
            [
                components.HashAnnouncerComponent,
                components.PeerProtocolServerComponent,
                components.FileManagerComponent,
                components.WalletServerPaymentsComponent
            ]
        ]
        self.component_manager = ComponentManager(Config())

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


class TestComponentManagerOverrides(AsyncioTestCase):

    def test_init_with_overrides(self):
        class FakeWallet:
            component_name = "wallet"
            depends_on = []

            def __init__(self, component_manager):
                self.component_manager = component_manager

            @property
            def component(self):
                return self

        new_component_manager = ComponentManager(Config(), wallet=FakeWallet)
        fake_wallet = new_component_manager.get_component("wallet")
        # wallet should be an instance of FakeWallet and not WalletComponent from components.py
        self.assertIsInstance(fake_wallet, FakeWallet)
        self.assertNotIsInstance(fake_wallet, components.WalletComponent)

    def test_init_with_wrong_overrides(self):
        class FakeRandomComponent:
            component_name = "someComponent"
            depends_on = []

        with self.assertRaises(SyntaxError):
            ComponentManager(Config(), randomComponent=FakeRandomComponent)


class FakeComponent:
    depends_on = []
    component_name = None

    def __init__(self, component_manager):
        self.component_manager = component_manager
        self._running = False

    @property
    def running(self):
        return self._running

    async def start(self):
        pass

    async def stop(self):
        pass

    @property
    def component(self):
        return self

    async def _setup(self):
        result = await self.start()
        self._running = True
        return result

    async def _stop(self):
        result = await self.stop()
        self._running = False
        return result

    async def get_status(self):
        return {}

    def __lt__(self, other):
        return self.component_name < other.component_name


class FakeDelayedWallet(FakeComponent):
    component_name = "wallet"
    depends_on = []

    async def stop(self):
        await asyncio.sleep(1)


class FakeDelayedBlobManager(FakeComponent):
    component_name = "blob_manager"
    depends_on = [FakeDelayedWallet.component_name]

    async def start(self):
        await asyncio.sleep(1)

    async def stop(self):
        await asyncio.sleep(1)


class FakeDelayedStreamManager(FakeComponent):
    component_name = "stream_manager"
    depends_on = [FakeDelayedBlobManager.component_name]

    async def start(self):
        await asyncio.sleep(1)


class TestComponentManagerProperStart(AdvanceTimeTestCase):

    def setUp(self):
        self.component_manager = ComponentManager(
            Config(),
            skip_components=[
                DATABASE_COMPONENT, DHT_COMPONENT, HASH_ANNOUNCER_COMPONENT,
                PEER_PROTOCOL_SERVER_COMPONENT, UPNP_COMPONENT,
                EXCHANGE_RATE_MANAGER_COMPONENT],
            wallet=FakeDelayedWallet,
            stream_manager=FakeDelayedStreamManager,
            blob_manager=FakeDelayedBlobManager
        )

    async def test_proper_starting_of_components(self):
        asyncio.create_task(self.component_manager.start())

        await self.advance(0)
        self.assertTrue(self.component_manager.get_component('wallet').running)
        self.assertFalse(self.component_manager.get_component('blob_manager').running)
        self.assertFalse(self.component_manager.get_component('stream_manager').running)

        await self.advance(1)
        self.assertTrue(self.component_manager.get_component('wallet').running)
        self.assertTrue(self.component_manager.get_component('blob_manager').running)
        self.assertFalse(self.component_manager.get_component('stream_manager').running)

        await self.advance(1)
        self.assertTrue(self.component_manager.get_component('wallet').running)
        self.assertTrue(self.component_manager.get_component('blob_manager').running)
        self.assertTrue(self.component_manager.get_component('stream_manager').running)

    async def test_proper_stopping_of_components(self):
        asyncio.create_task(self.component_manager.start())
        await self.advance(0)
        await self.advance(1)
        await self.advance(1)
        self.assertTrue(self.component_manager.get_component('wallet').running)
        self.assertTrue(self.component_manager.get_component('blob_manager').running)
        self.assertTrue(self.component_manager.get_component('stream_manager').running)

        asyncio.create_task(self.component_manager.stop())
        await self.advance(0)
        self.assertFalse(self.component_manager.get_component('stream_manager').running)
        self.assertTrue(self.component_manager.get_component('blob_manager').running)
        self.assertTrue(self.component_manager.get_component('wallet').running)
        await self.advance(1)
        self.assertFalse(self.component_manager.get_component('stream_manager').running)
        self.assertFalse(self.component_manager.get_component('blob_manager').running)
        self.assertTrue(self.component_manager.get_component('wallet').running)
        await self.advance(1)
        self.assertFalse(self.component_manager.get_component('stream_manager').running)
        self.assertFalse(self.component_manager.get_component('blob_manager').running)
        self.assertFalse(self.component_manager.get_component('wallet').running)
