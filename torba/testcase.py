import sys
import logging
import asyncio
from asyncio.runners import _cancel_all_tasks  # type: ignore
import unittest
from unittest.case import _Outcome
from typing import Optional
from torba.orchstr8 import Conductor
from torba.orchstr8.node import BlockchainNode, WalletNode
from torba.client.baseledger import BaseLedger
from torba.client.baseaccount import BaseAccount
from torba.client.basemanager import BaseWalletManager
from torba.client.wallet import Wallet
from torba.client.util import satoshis_to_coins


class ColorHandler(logging.StreamHandler):

    level_color = {
        logging.DEBUG: "black",
        logging.INFO: "light_gray",
        logging.WARNING: "yellow",
        logging.ERROR: "red"
    }

    color_code = dict(
        black=30,
        red=31,
        green=32,
        yellow=33,
        blue=34,
        magenta=35,
        cyan=36,
        white=37,
        light_gray='0;37',
        dark_gray='1;30'
    )

    def emit(self, record):
        try:
            msg = self.format(record)
            color_name = self.level_color.get(record.levelno, "black")
            color_code = self.color_code[color_name]
            stream = self.stream
            stream.write('\x1b[%sm%s\x1b[0m' % (color_code, msg))
            stream.write(self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)


HANDLER = ColorHandler(sys.stdout)
HANDLER.setFormatter(
    logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
)
logging.getLogger().addHandler(HANDLER)


class AsyncioTestCase(unittest.TestCase):
    # Implementation inspired by discussion:
    #  https://bugs.python.org/issue32972

    async def asyncSetUp(self):  # pylint: disable=C0103
        pass

    async def asyncTearDown(self):  # pylint: disable=C0103
        pass

    async def doAsyncCleanups(self):  # pylint: disable=C0103
        pass

    def run(self, result=None):  # pylint: disable=R0915
        orig_result = result
        if result is None:
            result = self.defaultTestResult()
            startTestRun = getattr(result, 'startTestRun', None)  # pylint: disable=C0103
            if startTestRun is not None:
                startTestRun()

        result.startTest(self)

        testMethod = getattr(self, self._testMethodName)  # pylint: disable=C0103
        if (getattr(self.__class__, "__unittest_skip__", False) or
                getattr(testMethod, "__unittest_skip__", False)):
            # If the class or method was skipped.
            try:
                skip_why = (getattr(self.__class__, '__unittest_skip_why__', '')
                            or getattr(testMethod, '__unittest_skip_why__', ''))
                self._addSkip(result, self, skip_why)
            finally:
                result.stopTest(self)
            return
        expecting_failure_method = getattr(testMethod,
                                           "__unittest_expecting_failure__", False)
        expecting_failure_class = getattr(self,
                                          "__unittest_expecting_failure__", False)
        expecting_failure = expecting_failure_class or expecting_failure_method
        outcome = _Outcome(result)
        try:
            self._outcome = outcome

            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.set_debug(True)

                with outcome.testPartExecutor(self):
                    self.setUp()
                    loop.run_until_complete(self.asyncSetUp())
                if outcome.success:
                    outcome.expecting_failure = expecting_failure
                    with outcome.testPartExecutor(self, isTest=True):
                        possible_coroutine = testMethod()
                        if asyncio.iscoroutine(possible_coroutine):
                            loop.run_until_complete(possible_coroutine)
                    outcome.expecting_failure = False
                    with outcome.testPartExecutor(self):
                        loop.run_until_complete(self.asyncTearDown())
                        self.tearDown()
            finally:
                try:
                    _cancel_all_tasks(loop)
                    loop.run_until_complete(loop.shutdown_asyncgens())
                finally:
                    asyncio.set_event_loop(None)
                    loop.close()

            self.doCleanups()

            for test, reason in outcome.skipped:
                self._addSkip(result, test, reason)
            self._feedErrorsToResult(result, outcome.errors)
            if outcome.success:
                if expecting_failure:
                    if outcome.expectedFailure:
                        self._addExpectedFailure(result, outcome.expectedFailure)
                    else:
                        self._addUnexpectedSuccess(result)
                else:
                    result.addSuccess(self)
            return result
        finally:
            result.stopTest(self)
            if orig_result is None:
                stopTestRun = getattr(result, 'stopTestRun', None)  # pylint: disable=C0103
                if stopTestRun is not None:
                    stopTestRun()  # pylint: disable=E1102

            # explicitly break reference cycles:
            # outcome.errors -> frame -> outcome -> outcome.errors
            # outcome.expectedFailure -> frame -> outcome -> outcome.expectedFailure
            outcome.errors.clear()
            outcome.expectedFailure = None

            # clear the outcome, no more needed
            self._outcome = None


class IntegrationTestCase(AsyncioTestCase):

    LEDGER = None
    MANAGER = None
    VERBOSITY = logging.WARN

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.conductor: Optional[Conductor] = None
        self.blockchain: Optional[BlockchainNode] = None
        self.wallet_node: Optional[WalletNode] = None
        self.manager: Optional[BaseWalletManager] = None
        self.ledger: Optional[BaseLedger] = None
        self.wallet: Optional[Wallet] = None
        self.account: Optional[BaseAccount] = None

    async def asyncSetUp(self):
        self.conductor = Conductor(
            ledger_module=self.LEDGER, manager_module=self.MANAGER, verbosity=self.VERBOSITY
        )
        await self.conductor.start()
        self.blockchain = self.conductor.blockchain_node
        self.wallet_node = self.conductor.wallet_node
        self.manager = self.wallet_node.manager
        self.ledger = self.wallet_node.ledger
        self.wallet = self.wallet_node.wallet
        self.account = self.wallet_node.wallet.default_account

    async def asyncTearDown(self):
        await self.conductor.stop()

    async def assertBalance(self, account, expected_balance: str):  # pylint: disable=C0103
        balance = await account.get_balance()
        self.assertEqual(satoshis_to_coins(balance), expected_balance)

    def broadcast(self, tx):
        return self.ledger.broadcast(tx)

    async def on_header(self, height):
        if self.ledger.headers.height < height:
            await self.ledger.on_header.where(
                lambda e: e.height == height
            )
        return True

    def on_transaction_id(self, txid, ledger=None):
        return (ledger or self.ledger).on_transaction.where(
            lambda e: e.tx.id == txid
        )

    def on_transaction_address(self, tx, address):
        return self.ledger.on_transaction.where(
            lambda e: e.tx.id == tx.id and e.address == address
        )
