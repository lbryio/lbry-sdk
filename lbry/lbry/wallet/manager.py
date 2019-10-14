import os
import json
import logging
from binascii import unhexlify


from torba.client.basemanager import BaseWalletManager
from torba.rpc.jsonrpc import CodeMessageError

from lbry.wallet.ledger import MainNetLedger
from lbry.wallet.transaction import Transaction
from lbry.wallet.database import WalletDatabase
from lbry.conf import Config


log = logging.getLogger(__name__)


class LbryWalletManager(BaseWalletManager):

    @property
    def ledger(self) -> MainNetLedger:
        return self.default_account.ledger

    @property
    def db(self) -> WalletDatabase:
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
        temp_path = "{}.tmp.{}".format(path, os.getpid())
        with open(temp_path, "w") as f:
            f.write(migrated_json)
            f.flush()
            os.fsync(f.fileno())
        os.rename(temp_path, path)
        os.chmod(path, mode)
        return receiving_addresses, change_addresses

    @classmethod
    async def from_lbrynet_config(cls, settings: Config):

        ledger_id = {
            'lbrycrd_main':    'lbc_mainnet',
            'lbrycrd_testnet': 'lbc_testnet',
            'lbrycrd_regtest': 'lbc_regtest'
        }[settings.blockchain_name]

        ledger_config = {
            'auto_connect': True,
            'default_servers': settings.lbryum_servers,
            'data_path': settings.wallet_dir,
        }

        wallets_directory = os.path.join(settings.wallet_dir, 'wallets')
        if not os.path.exists(wallets_directory):
            os.mkdir(wallets_directory)

        receiving_addresses, change_addresses = cls.migrate_lbryum_to_torba(
            os.path.join(wallets_directory, 'default_wallet')
        )

        manager = cls.from_config({
            'ledgers': {ledger_id: ledger_config},
            'wallets': [
                os.path.join(wallets_directory, wallet_file) for wallet_file in settings.wallets
            ]
        })
        ledger = manager.get_or_create_ledger(ledger_id)
        ledger.coin_selection_strategy = settings.coin_selection_strategy
        default_wallet = manager.default_wallet
        if default_wallet.default_account is None:
            log.info('Wallet at %s is empty, generating a default account.', default_wallet.id)
            default_wallet.generate_account(ledger)
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

    async def _migrate_addresses(self, receiving_addresses: set, change_addresses: set):
        async with self.default_account.receiving.address_generator_lock:
            migrated_receiving = set((await self.default_account.receiving._generate_keys(0, len(receiving_addresses))))
        async with self.default_account.change.address_generator_lock:
            migrated_change = set((await self.default_account.change._generate_keys(0, len(change_addresses))))
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

    def get_best_blockhash(self):
        if len(self.ledger.headers) <= 0:
            return self.ledger.genesis_hash
        return self.ledger.headers.hash(self.ledger.headers.height).decode()

    def get_unused_address(self):
        return self.default_account.receiving.get_or_create_usable_address()

    async def send_amount_to_address(self, amount: int, destination_address: bytes, account=None):
        account = account or self.default_account
        tx = await Transaction.pay(amount, destination_address, [account], account)
        await account.ledger.broadcast(tx)
        return tx

    async def get_transaction(self, txid):
        tx = await self.db.get_transaction(txid=txid)
        if not tx:
            try:
                raw = await self.ledger.network.get_transaction(txid)
                if not raw:
                    return {'success': False, 'code': 404, 'message': 'transaction not found'}
                height = await self.ledger.network.get_transaction_height(txid)
            except CodeMessageError as e:
                return {'success': False, 'code': e.code, 'message': e.message}
            tx = self.ledger.transaction_class(unhexlify(raw))
            await self.ledger.maybe_verify_transaction(tx, height)
        return tx
