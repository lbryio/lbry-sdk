import asyncio
from binascii import hexlify
from orchstr8.testcase import IntegrationTestCase
from torba.constants import COIN


class StartupTests(IntegrationTestCase):

    VERBOSE = True

    async def test_balance(self):
        account = self.wallet.default_account
        coin = account.coin
        ledger = self.manager.ledgers[coin.ledger_class]
        address = account.get_least_used_receiving_address()
        sendtxid = await self.lbrycrd.sendtoaddress(address.decode(), 2.5)
        await self.lbrycrd.generate(1)
        await ledger.on_transaction.where(
            lambda tx: tx.id.decode() == sendtxid
        )
        utxo = account.get_unspent_utxos()[0]
        address2 = account.get_least_used_receiving_address()
        tx_class = ledger.transaction_class
        Input, Output = tx_class.input_class, tx_class.output_class
        tx = tx_class() \
            .add_inputs([Input.spend(utxo)]) \
            .add_outputs([Output.pay_pubkey_hash(int(2.49*COIN), coin.address_to_hash160(address2))]) \
            .sign(account)
        await self.lbrycrd.decoderawtransaction(hexlify(tx.raw))
        sendtxid = await self.lbrycrd.sendrawtransaction(hexlify(tx.raw))
        await self.lbrycrd.generate(1)
        await ledger.on_transaction.where(
            lambda tx: tx.id.decode() == sendtxid
        )


class AbandonClaimLookup(IntegrationTestCase):

    async def skip_test_abandon_claim(self):
        address = yield self.lbry.wallet.get_least_used_address()
        yield self.lbrycrd.sendtoaddress(address, 0.0003 - 0.0000355)
        yield self.lbrycrd.generate(1)
        yield self.lbry.wallet.update_balance()
        yield threads.deferToThread(time.sleep, 5)
        print(self.lbry.wallet.get_balance())
        claim = yield self.lbry.wallet.claim_new_channel('@test', 0.000096)
        yield self.lbrycrd.generate(1)
        print('='*10 + 'CLAIM' + '='*10)
        print(claim)
        yield self.lbrycrd.decoderawtransaction(claim['tx'])
        abandon = yield self.lbry.wallet.abandon_claim(claim['claim_id'], claim['txid'], claim['nout'])
        print('='*10 + 'ABANDON' + '='*10)
        print(abandon)
        yield self.lbrycrd.decoderawtransaction(abandon['tx'])
        yield self.lbrycrd.generate(1)
        yield self.lbrycrd.getrawtransaction(abandon['txid'])

        yield self.lbry.wallet.update_balance()
        yield threads.deferToThread(time.sleep, 5)
        print('='*10 + 'FINAL BALANCE' + '='*10)
        print(self.lbry.wallet.get_balance())
