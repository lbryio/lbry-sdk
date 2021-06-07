import asyncio
import logging

from lbry.error import (
    ServerPaymentFeeAboveMaxAllowedError,
    ServerPaymentInvalidAddressError,
    ServerPaymentWalletLockedError
)
from lbry.wallet.dewies import lbc_to_dewies
from lbry.wallet.stream import StreamController
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
        self._on_payment_controller = StreamController()
        self.on_payment = self._on_payment_controller.stream
        self.on_payment.listen(None, on_error=lambda e: logging.warning(e.args[0]))

    async def pay(self):
        while self.running:
            await asyncio.sleep(self.payment_period)
            features = await self.ledger.network.retriable_call(self.ledger.network.get_server_features)
            address = features['payment_address']
            amount = str(features['daily_fee'])
            if not address or not amount:
                continue

            if not self.ledger.is_pubkey_address(address):
                self._on_payment_controller.add_error(ServerPaymentInvalidAddressError(address))
                continue

            if self.wallet.is_locked:
                self._on_payment_controller.add_error(ServerPaymentWalletLockedError())
                continue

            amount = lbc_to_dewies(features['daily_fee'])  # check that this is in lbc and not dewies
            limit = lbc_to_dewies(self.max_fee)
            if amount > limit:
                self._on_payment_controller.add_error(
                    ServerPaymentFeeAboveMaxAllowedError(features['daily_fee'], self.max_fee)
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
            self._on_payment_controller.add(tx)

    async def start(self, ledger=None, wallet=None):
        if lbc_to_dewies(self.max_fee) < 1:
            return
        self.ledger = ledger
        self.wallet = wallet
        self.running = True
        self.task = asyncio.ensure_future(self.pay())
        self.task.add_done_callback(lambda _: log.info("Stopping wallet server payments."))

    async def stop(self):
        if self.running:
            self.running = False
            self.task.cancel()
