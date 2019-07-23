import asyncio
import logging
from binascii import unhexlify
from typing import Tuple, List, Dict

from lbry.wallet.claim_proofs import verify_proof, InvalidProofError
from torba.client.baseledger import BaseLedger
from torba.client.baseaccount import SingleKey
from lbry.schema.result import Outputs
from lbry.schema.url import URL, normalize_name
from lbry.wallet.dewies import dewies_to_lbc
from lbry.wallet.resolve import Resolver
from lbry.wallet.account import Account
from lbry.wallet.network import Network
from lbry.wallet.database import WalletDatabase
from lbry.wallet.transaction import Transaction, Output
from lbry.wallet.header import Headers, UnvalidatedHeaders


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

    async def _inflate_outputs(self, query):
        outputs = Outputs.from_base64(await query)
        txs = []
        if len(outputs.txs) > 0:
            txs = await asyncio.gather(*(self.cache_transaction(*tx) for tx in outputs.txs))
        return outputs.inflate(txs), outputs.offset, outputs.total

    async def resolve(self, urls):
        txos = (await self._inflate_outputs(self.network.resolve(urls)))[0]
        assert len(urls) == len(txos), "Mismatch between urls requested for resolve and responses received."
        result = {}
        for url, txo in zip(urls, txos):
            if txo and URL.parse(url).has_stream_in_channel:
                if not txo.channel or not txo.is_signed_by(txo.channel, self):
                    txo = None
            if txo:
                result[url] = txo
            else:
                result[url] = {'error': f'{url} did not resolve to a claim'}
        return await self.validate_resolutions(result)

    async def validate_resolutions(self, resolutions: dict):
        provables = {}
        for url, txo in resolutions.items():
            if isinstance(txo, dict) and 'error' in txo:
                continue
            parsed_url = URL.parse(url)
            # cases we check: names without sequence, claim id or any modifier
            # except: @channel/name as the signature is enough, instead we check '@channel'
            if parsed_url.has_channel:
                if not parsed_url.has_stream_in_channel and parsed_url.channel.to_dict().keys() == {'name'}:
                    provables.setdefault(normalize_name(parsed_url.channel.name), []).append((url, txo.id))
            elif parsed_url.has_stream and parsed_url.stream.to_dict().keys() == {'name'}:
                provables.setdefault(normalize_name(parsed_url.stream.name), []).append((url, txo.id))
        if not provables:
            return resolutions
        root_hash = self.headers.claim_trie_root.decode()
        names = list(provables.keys())
        proofs = await self.network.get_name_proofs(self.headers.hash().decode(), *names)
        for proof, name in zip(proofs, names):
            all_failed = True
            for url, txid in provables[name]:
                if not proof.get('txhash'):
                    resolutions[url] = {'error': f"Proof mismatch on {url}: no claims under {name} but we got {txid}"}
                    continue
                expected_txid = f"{proof['txhash']}:{proof['nOut']}"
                if txid != expected_txid:
                    resolutions[url] = {
                        'error': f"Proof mismatch: {url} resolved to {txid} instead of {expected_txid} on {name}"
                    }
                else:
                    all_failed = False
            if not all_failed:
                try:
                    verify_proof(proof, root_hash, name)
                    continue
                except InvalidProofError as error:
                    for url, _ in provables[name]:
                        resolution = resolutions[url]
                        if isinstance(resolution, dict) and 'error' in resolution:
                            continue
                        resolutions[url] = {'error': f'Invalid proof for {url}: {str(error)}'}
        return resolutions

    async def claim_search(self, **kwargs) -> Tuple[List, int, int]:
        return await self._inflate_outputs(self.network.claim_search(**kwargs))

    async def get_claim_by_claim_id(self, claim_id) -> Dict[str, Output]:
        for claim in (await self.claim_search(claim_id=claim_id))[0]:
            return claim

    async def start(self):
        await super().start()
        await asyncio.gather(*(a.maybe_migrate_certificates() for a in self.accounts))
        await asyncio.gather(*(a.save_max_gap() for a in self.accounts))
        await self._report_state()

    async def _report_state(self):
        try:
            for account in self.accounts:
                balance = dewies_to_lbc(await account.get_balance())
                channel_count = await account.get_channel_count()
                claim_count = await account.get_claim_count()
                if isinstance(account.receiving, SingleKey):
                    log.info("Loaded single key account %s with %s LBC. "
                             "%d channels, %d certificates and %d claims",
                             account.id, balance, channel_count, len(account.channel_keys), claim_count)
                else:
                    total_receiving = len((await account.receiving.get_addresses()))
                    total_change = len((await account.change.get_addresses()))
                    log.info("Loaded account %s with %s LBC, %d receiving addresses (gap: %d), "
                             "%d change addresses (gap: %d), %d channels, %d certificates and %d claims. ",
                             account.id, balance, total_receiving, account.receiving.gap, total_change,
                             account.change.gap, channel_count, len(account.channel_keys), claim_count)
        except:
            log.exception(
                'Failed to display wallet state, please file issue '
                'for this bug along with the traceback you see below:')


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
