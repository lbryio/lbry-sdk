import time
import shutil
import logging
import tempfile
from binascii import hexlify

from twisted.internet import defer, reactor, threads
from twisted.trial import unittest
from orchstr8.wrapper import BaseLbryServiceStack

from lbrynet.core.call_later_manager import CallLaterManager
from lbrynet.database.storage import SQLiteStorage

from lbrynet.wallet import set_wallet_manager
from lbrynet.wallet.wallet import Wallet
from lbrynet.wallet.manager import WalletManager
from lbrynet.wallet.transaction import Transaction, Output
from lbrynet.wallet.constants import COIN, REGTEST_CHAIN
from lbrynet.wallet.hash import hash160_to_address, address_to_hash_160


class WalletTestCase(unittest.TestCase):

    VERBOSE = False

    def setUp(self):
        logging.getLogger('lbrynet').setLevel(logging.INFO)
        self.data_path = tempfile.mkdtemp()
        self.db = SQLiteStorage(self.data_path)
        self.config = {
            'chain': REGTEST_CHAIN,
            'wallet_path': self.data_path,
            'default_servers': [('localhost', 50001)]
        }
        CallLaterManager.setup(reactor.callLater)
        self.service = BaseLbryServiceStack(self.VERBOSE)
        return self.service.startup()

    def tearDown(self):
        CallLaterManager.stop()
        shutil.rmtree(self.data_path, ignore_errors=True)
        return self.service.shutdown()

    @property
    def lbrycrd(self):
        return self.service.lbrycrd


class StartupTests(WalletTestCase):

    VERBOSE = True

    @defer.inlineCallbacks
    def test_balance(self):
        wallet = Wallet(chain=REGTEST_CHAIN)
        manager = WalletManager(self.config, wallet)
        set_wallet_manager(manager)
        yield manager.start()
        yield self.lbrycrd.generate(1)
        yield threads.deferToThread(time.sleep, 1)
        #yield wallet.network.on_header.first
        address = manager.get_least_used_receiving_address()
        sendtxid = yield self.lbrycrd.sendtoaddress(address, 2.5)
        yield self.lbrycrd.generate(1)
        #yield manager.wallet.history.on_transaction.
        yield threads.deferToThread(time.sleep, 10)
        tx = manager.ledger.transactions.values()[0]
        print(tx.to_python_source())
        print(address)
        output = None
        for txo in tx.outputs:
            other = hash160_to_address(txo.script.values['pubkey_hash'], 'regtest')
            if other == address:
                output = txo
                break

        address2 = manager.get_least_used_receiving_address()
        tx = Transaction()
        tx.add_inputs([output.spend()])
        Output.pay_pubkey_hash(tx, 0, 2.49*COIN, address_to_hash_160(address2))
        print(tx.to_python_source())
        tx.sign(wallet)
        print(tx.to_python_source())

        yield self.lbrycrd.decoderawtransaction(hexlify(tx.raw))
        yield self.lbrycrd.sendrawtransaction(hexlify(tx.raw))

        yield manager.stop()
