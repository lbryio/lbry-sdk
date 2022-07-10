import unittest
import asyncio
from lbry import utils
from lbry.testcase import AsyncioTestCase


class CompareVersionTest(unittest.TestCase):
    def test_compare_versions_isnot_lexographic(self):
        self.assertTrue(utils.version_is_greater_than('0.3.10', '0.3.6'))

    def test_same_versions_return_false(self):
        self.assertFalse(utils.version_is_greater_than('1.3.9', '1.3.9'))

    def test_same_release_is_greater_then_beta(self):
        self.assertTrue(utils.version_is_greater_than('1.3.9', '1.3.9b1'))

    def test_version_can_have_four_parts(self):
        self.assertTrue(utils.version_is_greater_than('1.3.9.1', '1.3.9'))

    def test_release_is_greater_than_rc(self):
        self.assertTrue(utils.version_is_greater_than('1.3.9', '1.3.9rc0'))


class ObfuscationTest(unittest.TestCase):
    def test_deobfuscation_reverses_obfuscation(self):
        plain = "my_test_string"
        obf = utils.obfuscate(plain.encode())
        self.assertEqual(plain, utils.deobfuscate(obf))

    def test_can_use_unicode(self):
        plain = '☃'
        obf = utils.obfuscate(plain.encode())
        self.assertEqual(plain, utils.deobfuscate(obf))


class SdHashTests(unittest.TestCase):

    def test_none_in_none_out(self):
        self.assertIsNone(utils.get_sd_hash(None))

    def test_ordinary_dict(self):
        claim = {
            "claim": {
                "value": {
                    "stream": {
                        "source": {
                            "source": "0123456789ABCDEF"
                        }
                    }
                }
            }
        }
        self.assertEqual("0123456789ABCDEF", utils.get_sd_hash(claim))

    def test_old_shape_fails(self):
        claim = {
            "stream": {
                "source": {
                    "source": "0123456789ABCDEF"
                }
            }
        }
        self.assertIsNone(utils.get_sd_hash(claim))


class CacheConcurrentDecoratorTests(AsyncioTestCase):
    def setUp(self):
        self.called = []
        self.finished = []
        self.counter = 0

    @utils.cache_concurrent
    async def foo(self, arg1, arg2=None, delay=1):
        self.called.append((arg1, arg2, delay))
        await asyncio.sleep(delay)
        self.counter += 1
        self.finished.append((arg1, arg2, delay))
        return object()

    async def test_gather_duplicates(self):
        result = await asyncio.gather(
            self.loop.create_task(self.foo(1)), self.loop.create_task(self.foo(1))
        )
        self.assertEqual(1, len(self.called))
        self.assertEqual(1, len(self.finished))
        self.assertEqual(1, self.counter)
        self.assertIs(result[0], result[1])
        self.assertEqual(2, len(result))

    async def test_one_cancelled_all_cancel(self):
        t1 = self.loop.create_task(self.foo(1))
        self.loop.call_later(0.1, t1.cancel)

        with self.assertRaises(asyncio.CancelledError):
            await asyncio.gather(
                t1, self.loop.create_task(self.foo(1))
            )
        self.assertEqual(1, len(self.called))
        self.assertEqual(0, len(self.finished))
        self.assertEqual(0, self.counter)

    async def test_error_after_success(self):
        def cause_type_error():
            self.counter = ""

        self.loop.call_later(0.1, cause_type_error)

        t1 = self.loop.create_task(self.foo(1))
        t2 = self.loop.create_task(self.foo(1))

        with self.assertRaises(TypeError):
            await t2
        self.assertEqual(1, len(self.called))
        self.assertEqual(0, len(self.finished))
        self.assertTrue(t1.done())
        self.assertEqual("", self.counter)

        # test that the task is run fresh, it should not error
        self.counter = 0
        t3 = self.loop.create_task(self.foo(1))
        self.assertTrue(await t3)
        self.assertEqual(1, self.counter)

        # the previously failed call should still raise if awaited
        with self.assertRaises(TypeError):
            await t1

        self.assertEqual(1, self.counter)

    async def test_break_it(self):
        t1 = self.loop.create_task(self.foo(1))
        t2 = self.loop.create_task(self.foo(1))
        t3 = self.loop.create_task(self.foo(2, delay=0))
        t3.add_done_callback(lambda _: t2.cancel())
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.gather(t1, t2, t3)
