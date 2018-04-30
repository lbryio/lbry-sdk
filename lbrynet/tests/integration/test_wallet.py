import time
import shutil
import logging
import tempfile
from binascii import hexlify

from twisted.internet import defer, reactor, threads
from twisted.trial import unittest
from orchstr8.services import BaseLbryServiceStack

from lbrynet.core.call_later_manager import CallLaterManager
from lbrynet.database.storage import SQLiteStorage

from lbrynet.wallet.basecoin import CoinRegistry
from lbrynet.wallet.manager import WalletManager
from lbrynet.wallet.constants import COIN


class WalletTestCase(unittest.TestCase):

    VERBOSE = False

    def setUp(self):
        logging.getLogger('lbrynet').setLevel(logging.INFO)
        self.data_path = tempfile.mkdtemp()
        self.db = SQLiteStorage(self.data_path)
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
        coin_id = 'lbc_regtest'
        manager = WalletManager.from_config({
            'ledgers': {coin_id: {'default_servers': [('localhost', 50001)]}}
        })
        wallet = manager.create_wallet(None, CoinRegistry.get_coin_class(coin_id))
        ledger = manager.ledgers.values()[0]
        account = wallet.default_account
        coin = account.coin
        yield manager.start_ledgers()
        address = account.get_least_used_receiving_address()
        sendtxid = yield self.lbrycrd.sendtoaddress(address, 2.5)
        yield self.lbrycrd.generate(1)
        #yield manager.wallet.history.on_transaction.
        yield threads.deferToThread(time.sleep, 10)
        utxo = account.get_unspent_utxos()[0]
        address2 = account.get_least_used_receiving_address()
        tx_class = ledger.transaction_class
        Input, Output = tx_class.input_class, tx_class.output_class
        tx = tx_class()\
            .add_inputs([Input.spend(utxo)])\
            .add_outputs([Output.pay_pubkey_hash(2.49*COIN, coin.address_to_hash160(address2))])\
            .sign(account)

        yield self.lbrycrd.decoderawtransaction(hexlify(tx.raw))
        yield self.lbrycrd.sendrawtransaction(hexlify(tx.raw))

        yield manager.stop_ledgers()
