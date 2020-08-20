import os
import time
import asyncio
import signal
from threading import Thread
from unittest import TestCase

from lbry import Daemon, FullNode
from lbry.console import Console
from lbry.blockchain.lbrycrd import Lbrycrd


class TestShutdown(TestCase):

    def test_graceful_fail(self):
        chain_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(chain_loop)
        chain = Lbrycrd.temp_regtest()
        self.addCleanup(lambda: chain_loop.run_until_complete(chain.stop()))
        self.addCleanup(lambda: asyncio.set_event_loop(chain_loop))
        chain_loop.run_until_complete(chain.ensure())
        chain_loop.run_until_complete(chain.start())
        chain_loop.run_until_complete(chain.generate(1))
        chain.ledger.conf.set(workers=2)
        service = FullNode(chain.ledger)
        daemon = Daemon(service, Console(service))

        def send_signal():
            time.sleep(2)
            os.kill(os.getpid(), signal.SIGTERM)

        thread = Thread(target=send_signal)
        thread.start()

        daemon.run()
