import asyncio
from torba.testcase import AsyncioTestCase
from lbrynet.dht.peer_finder import AsyncGeneratorJunction


class MockAsyncGen:
    def __init__(self, loop, result, delay, stop_cnt=10):
        self.loop = loop
        self.result = result
        self.delay = delay
        self.count = 0
        self.stop_cnt = stop_cnt
        self.called_close = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.count > self.stop_cnt - 1:
            raise StopAsyncIteration()
        self.count += 1
        await asyncio.sleep(self.delay, loop=self.loop)
        return self.result

    def aclose(self):
        self.called_close = True


class TestAsyncGeneratorJunction(AsyncioTestCase):
    def setUp(self):
        self.loop = asyncio.get_event_loop()

    async def _test_junction(self, expected, *generators):
        junction = AsyncGeneratorJunction(self.loop)
        for generator in generators:
            junction.add_generator(generator)
        order = []
        async for item in junction:
            order.append(item)
        self.assertListEqual(order, expected)

    async def test_yield_order(self):
        expected_order = [1, 2, 1, 1, 2, 1, 1, 2, 1, 1, 2, 1, 1, 2, 1, 2, 2, 2, 2, 2]
        fast_gen = MockAsyncGen(self.loop, 1, 0.01)
        slow_gen = MockAsyncGen(self.loop, 2, 0.02)
        await self._test_junction(expected_order, fast_gen, slow_gen)
        self.assertEqual(fast_gen.called_close, True)
        self.assertEqual(slow_gen.called_close, True)

    async def test_one_stopped_first(self):
        expected_order = [1, 2, 1, 1, 2, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2]
        fast_gen = MockAsyncGen(self.loop, 1, 0.01, 5)
        slow_gen = MockAsyncGen(self.loop, 2, 0.02)
        await self._test_junction(expected_order, fast_gen, slow_gen)
        self.assertEqual(fast_gen.called_close, True)
        self.assertEqual(slow_gen.called_close, True)

    async def test_with_non_async_gen_class(self):
        expected_order = [1, 2, 1, 1, 2, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2]

        async def fast_gen():
            for i in range(10):
                if i == 5:
                    return
                await asyncio.sleep(0.01)
                yield 1

        slow_gen = MockAsyncGen(self.loop, 2, 0.02)
        await self._test_junction(expected_order, fast_gen(), slow_gen)
        self.assertEqual(slow_gen.called_close, True)
