import asyncio
import logging
from binascii import unhexlify

from torba.client.baseledger import BaseLedger
from lbrynet.schema.error import URIParseError
from lbrynet.schema.uri import parse_lbry_uri
from lbrynet.extras.wallet.dewies import dewies_to_lbc
from lbrynet.extras.wallet.resolve import Resolver
from lbrynet.extras.wallet.account import Account
from lbrynet.extras.wallet.network import Network
from lbrynet.extras.wallet.database import WalletDatabase
from lbrynet.extras.wallet.transaction import Transaction
from lbrynet.extras.wallet.header import Headers, UnvalidatedHeaders


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

    @property
    def resolver(self):
        return Resolver(self.headers.claim_trie_root, self.headers.height, self.transaction_class,
                        hash160_to_address=self.hash160_to_address, network=self.network)

    async def resolve(self, page, page_size, *uris):
        for uri in uris:
            try:
                parse_lbry_uri(uri)
                resolutions = await self.network.get_values_for_uris(self.headers.hash().decode(), *uris)
            except URIParseError as err:
                return {'error': err.args[0]}
            except Exception as e:
                return {'error': str(e)}
        return await self.resolver._handle_resolutions(resolutions, uris, page, page_size)

    async def get_claim_by_claim_id(self, claim_id):
        result = (await self.network.get_claims_by_ids(claim_id)).pop(claim_id, {})
        return await self.resolver.get_certificate_and_validate_result(result)

    async def get_claim_by_outpoint(self, txid, nout):
        claims = (await self.network.get_claims_in_tx(txid)) or []
        for claim in claims:
            if claim['nout'] == nout:
                return await self.resolver.get_certificate_and_validate_result(claim)
        return 'claim not found'

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
                     channel_count, len(account.certificates), claim_count)


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
