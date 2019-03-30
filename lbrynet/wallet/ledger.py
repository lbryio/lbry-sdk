import asyncio
import logging
from binascii import unhexlify
from typing import Optional

from torba.client.baseledger import BaseLedger
from lbrynet.schema.page import Page
from lbrynet.wallet.dewies import dewies_to_lbc
from lbrynet.wallet.resolve import Resolver
from lbrynet.wallet.account import Account
from lbrynet.wallet.network import Network
from lbrynet.wallet.database import WalletDatabase
from lbrynet.wallet.transaction import Transaction, Output
from lbrynet.wallet.header import Headers, UnvalidatedHeaders


log = logging.getLogger(__name__)


class MainNetLedger(BaseLedger):
    name = 'LBRY Credits'
    symbol = 'LBC'
    network_name = 'mainnet'

    headers: Headers

    account_class = Account
    database_class = WalletDatabase
    headers_class = Headers
    network_class = Network
    transaction_class = Transaction

    db: WalletDatabase

    secret_prefix = bytes((0x1c,))
    pubkey_address_prefix = bytes((0x55,))
    script_address_prefix = bytes((0x7a,))
    extended_public_key_prefix = unhexlify('0488b21e')
    extended_private_key_prefix = unhexlify('0488ade4')

    max_target = 0x0000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '9c89283ba0f3227f6c03b70216b9f665f0118d5e0fa729cedf4fb34d6a34f463'
    genesis_bits = 0x1f00ffff
    target_timespan = 150

    default_fee_per_byte = 50
    default_fee_per_name_char = 200000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fee_per_name_char = self.config.get('fee_per_name_char', self.default_fee_per_name_char)
        self.resolver = Resolver(self)

    def resolve(self, page, page_size, *uris):
        return self.resolver.resolve(page, page_size, *uris)

    async def claim_search(self, **kwargs) -> Page:
        return Page.from_base64(await self.network.claim_search(**kwargs))

    async def get_claim_by_claim_id(self, claim_id) -> Optional[Output]:
        page = await self.claim_search(claim_id=claim_id)
        if page.txos:
            return page.txos[0]

    async def get_claim_by_outpoint(self, txid, nout) -> Optional[Output]:
        page = await self.claim_search(txid=txid, nout=nout)
        if page.txos:
            return page.txos[0]

    async def start(self):
        await super().start()
        await asyncio.gather(*(a.maybe_migrate_certificates() for a in self.accounts))
        await asyncio.gather(*(a.save_max_gap() for a in self.accounts))
        await self._report_state()

    async def _report_state(self):
        for account in self.accounts:
            total_receiving = len((await account.receiving.get_addresses()))
            total_change = len((await account.change.get_addresses()))
            channel_count = await account.get_channel_count()
            claim_count = await account.get_claim_count()
            balance = dewies_to_lbc(await account.get_balance())
            log.info("Loaded account %s with %s LBC, %d receiving addresses (gap: %d), "
                     "%d change addresses (gap: %d), %d channels, %d certificates and %d claims. ",
                     account.id, balance, total_receiving, account.receiving.gap, total_change, account.change.gap,
                     channel_count, len(account.channel_keys), claim_count)


class TestNetLedger(MainNetLedger):
    network_name = 'testnet'
    pubkey_address_prefix = bytes((111,))
    script_address_prefix = bytes((196,))
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')


class RegTestLedger(MainNetLedger):
    network_name = 'regtest'
    headers_class = UnvalidatedHeaders
    pubkey_address_prefix = bytes((111,))
    script_address_prefix = bytes((196,))
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')

    max_target = 0x7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '6e3fcf1299d4ec5d79c3a4c91d624a4acf9e2e173d95a1a0504f677669687556'
    genesis_bits = 0x207fffff
    target_timespan = 1
