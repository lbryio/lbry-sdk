import asyncio
import logging

from lbry.wallet.dewies import lbc_to_dewies
from lbry.wallet.transaction import Output, Transaction

log = logging.getLogger(__name__)


class WalletServerPayer:
    def __init__(self, payment_period=24 * 60 * 60, max_fee='1.0', analytics_manager=None):
        self.ledger = None
        self.wallet = None
        self.running = False
        self.task = None
        self.payment_period = payment_period
        self.analytics_manager = analytics_manager
        self.max_fee = max_fee

    async def pay(self):
        while self.running:
            await asyncio.sleep(self.payment_period)
            features = await self.ledger.network.get_server_features()
            address = features['payment_address']
            amount = str(features['daily_fee'])
            if not address or not amount:
                continue

            if not self.ledger.is_valid_address(address):
                log.warning("Invalid address from wallet server: '%s' - skipping payment round.", address)
                continue
            if self.wallet.is_locked:
                log.warning("Cannot spend funds with locked wallet, skipping payment round.")
                continue

            amount = lbc_to_dewies(features['daily_fee'])  # check that this is in lbc and not dewies
            limit = lbc_to_dewies(self.max_fee)
            if amount > limit:
                log.warning(
                    "Server asked %s LBC as daily fee, but maximum allowed is %s LBC. Skipping payment round.",
                    features['daily_fee'], self.max_fee
                )
                continue

            tx = await Transaction.create(
                [],
                [Output.pay_pubkey_hash(amount, self.ledger.address_to_hash160(address))],
                self.wallet.get_accounts_or_all(None),
                self.wallet.get_account_or_default(None)
            )

            await self.ledger.broadcast(tx)
            if self.analytics_manager:
                await self.analytics_manager.send_credits_sent()

    async def start(self, ledger=None, wallet=None):
        self.ledger = ledger
        self.wallet = wallet
        self.running = True
        self.task = asyncio.ensure_future(self.pay())
        self.task.add_done_callback(lambda _: log.info("Stopping wallet server payments."))

    async def stop(self):
        if self.running:
            self.running = False
            self.task.cancel()
