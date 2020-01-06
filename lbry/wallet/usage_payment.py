import asyncio
import logging

from lbry.wallet import Wallet
from lbry.wallet.ledger import Ledger
from lbry.wallet.dewies import lbc_to_dewies
from lbry.wallet.transaction import Output, Transaction

log = logging.getLogger(__name__)


class WalletServerPayer:

    def __init__(self, ledger: Ledger, wallet: Wallet):
        self.ledger = ledger
        self.wallet = wallet
        self.running = False
        self.task = None

    async def pay(self):
        while self.running:
            await asyncio.sleep(24 * 60 * 60)
            features = await self.ledger.network.get_server_features()
            address = features['payment_address']

            if not self.ledger.is_valid_address(address):
                raise Exception(f"Invalid address: {address}")
            if self.wallet.is_locked:
                raise Exception("Cannot spend funds with locked wallet")

            amount = lbc_to_dewies(features['daily_fee'])  # check that this is in lbc and not dewies
            # todo: check that amount is less than our max

            tx = await Transaction.create([],
                                          [Output.pay_pubkey_hash(amount, self.ledger.address_to_hash160(address))],
                                          self.wallet.get_accounts_or_all(None),
                                          self.wallet.get_account_or_default(None))

            await self.ledger.broadcast(tx)
            await self.analytics_manager.send_credits_sent()

    async def start(self):
        self.running = True
        self.task = asyncio.ensure_future(self.pay())
        self.task.add_done_callback(lambda _: log.info("Stopping wallet server payments."))

    async def stop(self):
        if self.running:
            self.running = False
            self.task.cancel()
