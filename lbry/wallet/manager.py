import os
import json
import typing
import logging
import asyncio
from binascii import unhexlify
from decimal import Decimal
from typing import List, Type, MutableSequence, MutableMapping, Optional

from lbry.error import KeyFeeAboveMaxAllowedError
from lbry.conf import Config

from .dewies import dewies_to_lbc
from .account import Account
from .ledger import Ledger, LedgerRegistry
from .transaction import Transaction, Output
from .database import Database
from .wallet import Wallet, WalletStorage, ENCRYPT_ON_DISK
from .rpc.jsonrpc import CodeMessageError

if typing.TYPE_CHECKING:
    from lbry.extras.daemon.exchange_rate_manager import ExchangeRateManager


log = logging.getLogger(__name__)


class WalletManager:

    def __init__(self, wallets: MutableSequence[Wallet] = None,
                 ledgers: MutableMapping[Type[Ledger], Ledger] = None) -> None:
        self.wallets = wallets or []
        self.ledgers = ledgers or {}
        self.running = False
        self.config: Optional[Config] = None

    @classmethod
    def from_config(cls, config: dict) -> 'WalletManager':
        manager = cls()
        for ledger_id, ledger_config in config.get('ledgers', {}).items():
            manager.get_or_create_ledger(ledger_id, ledger_config)
        for wallet_path in config.get('wallets', []):
            wallet_storage = WalletStorage(wallet_path)
            wallet = Wallet.from_storage(wallet_storage, manager)
            manager.wallets.append(wallet)
        return manager

    def get_or_create_ledger(self, ledger_id, ledger_config=None):
        ledger_class = LedgerRegistry.get_ledger_class(ledger_id)
        ledger = self.ledgers.get(ledger_class)
        if ledger is None:
            ledger = ledger_class(ledger_config or {})
            self.ledgers[ledger_class] = ledger
        return ledger

    def import_wallet(self, path):
        storage = WalletStorage(path)
        wallet = Wallet.from_storage(storage, self)
        self.wallets.append(wallet)
        return wallet

    @property
    def default_wallet(self):
        for wallet in self.wallets:
            return wallet

    @property
    def default_account(self):
        for wallet in self.wallets:
            return wallet.default_account

    @property
    def accounts(self):
        for wallet in self.wallets:
            yield from wallet.accounts

    async def start(self):
        self.running = True
        await asyncio.gather(*(
            l.start() for l in self.ledgers.values()
        ))

    async def stop(self):
        await asyncio.gather(*(
            l.stop() for l in self.ledgers.values()
        ))
        self.running = False

    def get_wallet_or_default(self, wallet_id: Optional[str]) -> Wallet:
        if wallet_id is None:
            return self.default_wallet
        return self.get_wallet_or_error(wallet_id)

    def get_wallet_or_error(self, wallet_id: str) -> Wallet:
        for wallet in self.wallets:
            if wallet.id == wallet_id:
                return wallet
        raise ValueError(f"Couldn't find wallet: {wallet_id}.")

    @staticmethod
    def get_balance(wallet):
        accounts = wallet.accounts
        if not accounts:
            return 0
        return accounts[0].ledger.db.get_balance(wallet=wallet, accounts=accounts)

    @property
    def ledger(self) -> Ledger:
        return self.default_account.ledger

    @property
    def db(self) -> Database:
        return self.ledger.db

    def check_locked(self):
        return self.default_wallet.is_locked

    @staticmethod
    def migrate_lbryum_to_torba(path):
        if not os.path.exists(path):
            return None, None
        with open(path, 'r') as f:
            unmigrated_json = f.read()
            unmigrated = json.loads(unmigrated_json)
        # TODO: After several public releases of new torba based wallet, we can delete
        #       this lbryum->torba conversion code and require that users who still
        #       have old structured wallets install one of the earlier releases that
        #       still has the below conversion code.
        if 'master_public_keys' not in unmigrated:
            return None, None
        total = unmigrated.get('addr_history')
        receiving_addresses, change_addresses = set(), set()
        for _, unmigrated_account in unmigrated.get('accounts', {}).items():
            receiving_addresses.update(map(unhexlify, unmigrated_account.get('receiving', [])))
            change_addresses.update(map(unhexlify, unmigrated_account.get('change', [])))
        log.info("Wallet migrator found %s receiving addresses and %s change addresses. %s in total on history.",
                 len(receiving_addresses), len(change_addresses), len(total))

        migrated_json = json.dumps({
            'version': 1,
            'name': 'My Wallet',
            'accounts': [{
                'version': 1,
                'name': 'Main Account',
                'ledger': 'lbc_mainnet',
                'encrypted': unmigrated['use_encryption'],
                'seed': unmigrated['seed'],
                'seed_version': unmigrated['seed_version'],
                'private_key': unmigrated['master_private_keys']['x/'],
                'public_key': unmigrated['master_public_keys']['x/'],
                'certificates': unmigrated.get('claim_certificates', {}),
                'address_generator': {
                    'name': 'deterministic-chain',
                    'receiving': {'gap': 20, 'maximum_uses_per_address': 1},
                    'change': {'gap': 6, 'maximum_uses_per_address': 1}
                }
            }]
        }, indent=4, sort_keys=True)
        mode = os.stat(path).st_mode
        i = 1
        backup_path_template = os.path.join(os.path.dirname(path), "old_lbryum_wallet") + "_%i"
        while os.path.isfile(backup_path_template % i):
            i += 1
        os.rename(path, backup_path_template % i)
        temp_path = f"{path}.tmp.{os.getpid()}"
        with open(temp_path, "w") as f:
            f.write(migrated_json)
            f.flush()
            os.fsync(f.fileno())
        os.rename(temp_path, path)
        os.chmod(path, mode)
        return receiving_addresses, change_addresses

    @classmethod
    async def from_lbrynet_config(cls, config: Config):

        ledger_id = {
            'lbrycrd_main':    'lbc_mainnet',
            'lbrycrd_testnet': 'lbc_testnet',
            'lbrycrd_regtest': 'lbc_regtest'
        }[config.blockchain_name]

        ledger_config = {
            'auto_connect': True,
            'hub_timeout': config.hub_timeout,
            'default_servers': config.lbryum_servers,
            'data_path': config.wallet_dir,
            'tx_cache_size': config.transaction_cache_size
        }

        wallets_directory = os.path.join(config.wallet_dir, 'wallets')
        if not os.path.exists(wallets_directory):
            os.mkdir(wallets_directory)

        receiving_addresses, change_addresses = cls.migrate_lbryum_to_torba(
            os.path.join(wallets_directory, 'default_wallet')
        )

        manager = cls.from_config({
            'ledgers': {ledger_id: ledger_config},
            'wallets': [
                os.path.join(wallets_directory, wallet_file) for wallet_file in config.wallets
            ]
        })
        manager.config = config
        ledger = manager.get_or_create_ledger(ledger_id)
        ledger.coin_selection_strategy = config.coin_selection_strategy
        default_wallet = manager.default_wallet
        if default_wallet.default_account is None:
            log.info('Wallet at %s is empty, generating a default account.', default_wallet.id)
            default_wallet.generate_account(ledger)
            default_wallet.save()
        if default_wallet.is_locked and default_wallet.preferences.get(ENCRYPT_ON_DISK) is None:
            default_wallet.preferences[ENCRYPT_ON_DISK] = True
            default_wallet.save()
        if receiving_addresses or change_addresses:
            if not os.path.exists(ledger.path):
                os.mkdir(ledger.path)
            await ledger.db.open()
            try:
                await manager._migrate_addresses(receiving_addresses, change_addresses)
            finally:
                await ledger.db.close()
        return manager

    async def reset(self):
        self.ledger.config = {
            'auto_connect': True,
            'default_servers': self.config.lbryum_servers,
            'hub_timeout': self.config.hub_timeout,
            'data_path': self.config.wallet_dir,
        }
        await self.ledger.stop()
        await self.ledger.start()

    async def _migrate_addresses(self, receiving_addresses: set, change_addresses: set):
        async with self.default_account.receiving.address_generator_lock:
            migrated_receiving = set(await self.default_account.receiving._generate_keys(0, len(receiving_addresses)))
        async with self.default_account.change.address_generator_lock:
            migrated_change = set(await self.default_account.change._generate_keys(0, len(change_addresses)))
        receiving_addresses = set(map(self.default_account.ledger.public_key_to_address, receiving_addresses))
        change_addresses = set(map(self.default_account.ledger.public_key_to_address, change_addresses))
        if not any(change_addresses.difference(migrated_change)):
            log.info("Successfully migrated %s change addresses.", len(change_addresses))
        else:
            log.warning("Failed to migrate %s change addresses!",
                        len(set(change_addresses).difference(set(migrated_change))))
        if not any(receiving_addresses.difference(migrated_receiving)):
            log.info("Successfully migrated %s receiving addresses.", len(receiving_addresses))
        else:
            log.warning("Failed to migrate %s receiving addresses!",
                        len(set(receiving_addresses).difference(set(migrated_receiving))))

    async def get_best_blockhash(self):
        if len(self.ledger.headers) <= 0:
            return self.ledger.genesis_hash
        return (await self.ledger.headers.hash(self.ledger.headers.height)).decode()

    def get_unused_address(self):
        return self.default_account.receiving.get_or_create_usable_address()

    async def get_transaction(self, txid: str):
        tx = await self.db.get_transaction(txid=txid)
        if tx:
            return tx
        try:
            raw, merkle = await self.ledger.network.get_transaction_and_merkle(txid)
        except CodeMessageError as e:
            if 'No such mempool or blockchain transaction.' in e.message:
                return {'success': False, 'code': 404, 'message': 'transaction not found'}
            return {'success': False, 'code': e.code, 'message': e.message}
        height = merkle.get('block_height')
        tx = Transaction(unhexlify(raw), height=height)
        if height and height > 0:
            await self.ledger.maybe_verify_transaction(tx, height, merkle)
        return tx

    async def create_purchase_transaction(
            self, accounts: List[Account], txo: Output, exchange: 'ExchangeRateManager',
            override_max_key_fee=False):
        fee = txo.claim.stream.fee
        fee_amount = exchange.to_dewies(fee.currency, fee.amount)
        if not override_max_key_fee and self.config.max_key_fee:
            max_fee = self.config.max_key_fee
            max_fee_amount = exchange.to_dewies(max_fee['currency'], Decimal(max_fee['amount']))
            if max_fee_amount and fee_amount > max_fee_amount:
                error_fee = f"{dewies_to_lbc(fee_amount)} LBC"
                if fee.currency != 'LBC':
                    error_fee += f" ({fee.amount} {fee.currency})"
                error_max_fee = f"{dewies_to_lbc(max_fee_amount)} LBC"
                if max_fee['currency'] != 'LBC':
                    error_max_fee += f" ({max_fee['amount']} {max_fee['currency']})"
                raise KeyFeeAboveMaxAllowedError(
                    f"Purchase price of {error_fee} exceeds maximum "
                    f"configured price of {error_max_fee}."
                )
        fee_address = fee.address or txo.get_address(self.ledger)
        return await Transaction.purchase(
            txo.claim_id, fee_amount, fee_address, accounts, accounts[0]
        )

    async def broadcast_or_release(self, tx, blocking=False):
        try:
            await self.ledger.broadcast(tx)
        except:
            await self.ledger.release_tx(tx)
            raise
        if blocking:
            await self.ledger.wait(tx, timeout=None)
