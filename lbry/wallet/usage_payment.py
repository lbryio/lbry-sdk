import asyncio
import logging

from lbry.error import (
    InsufficientFundsError,
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
        self.on_payment.listen(None, on_error=lambda e: log.warning(e.args[0]))

    async def pay(self):
        while self.running:
            try:
                await self._pay()
            except (asyncio.TimeoutError, ConnectionError):
                if not self.running:
                    break
                delay = max(self.payment_period / 24, 10)
                log.warning("Payement failed. Will retry after %g seconds.", delay)
                asyncio.sleep(delay)
            except Exception:
                log.exception("Unexpected exception. Payment task exiting early.")
                raise

    async def _pay(self):
        while self.running:
            await asyncio.sleep(self.payment_period)
            features = await self.ledger.network.get_server_features()
            log.debug("pay loop: received server features: %s", str(features))
            address = features['payment_address']
            amount = str(features['daily_fee'])
            if not address or not amount:
                log.debug("pay loop: no address or no amount")
                continue

            if not self.ledger.is_pubkey_address(address):
                log.info("pay loop: address not pubkey")
                self._on_payment_controller.add_error(ServerPaymentInvalidAddressError(address))
                continue

            if self.wallet.is_locked:
                log.info("pay loop: wallet is locked")
                self._on_payment_controller.add_error(ServerPaymentWalletLockedError())
                continue

            amount = lbc_to_dewies(features['daily_fee'])  # check that this is in lbc and not dewies
            limit = lbc_to_dewies(self.max_fee)
            if amount > limit:
                log.info("pay loop: amount (%d) > limit (%d)", amount, limit)
                self._on_payment_controller.add_error(
                    ServerPaymentFeeAboveMaxAllowedError(features['daily_fee'], self.max_fee)
                )
                continue

            try:
                tx = await Transaction.create(
                    [],
                    [Output.pay_pubkey_hash(amount, self.ledger.address_to_hash160(address))],
                    self.wallet.get_accounts_or_all(None),
                    self.wallet.get_account_or_default(None)
                )
            except InsufficientFundsError as e:
                self._on_payment_controller.add_error(e)
                continue

            await self.ledger.broadcast_or_release(tx, blocking=True)
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
        self.task.add_done_callback(self._done_callback)

    def _done_callback(self, f):
        if f.cancelled():
            reason = "Cancelled"
        elif not self.running:
            reason = "Stopped"
        else:
            reason = f'Exception: {f.exception()}'
        log.info("Stopping wallet server payments. %s", reason)

    async def stop(self):
        if self.running:
            self.running = False
            self.task.cancel()
