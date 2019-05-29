import os
import json
import logging
from binascii import unhexlify

from datetime import datetime

from torba.client.basemanager import BaseWalletManager
from torba.rpc.jsonrpc import CodeMessageError

from lbrynet.wallet.ledger import MainNetLedger
from lbrynet.wallet.account import BaseAccount
from lbrynet.wallet.transaction import Transaction
from lbrynet.wallet.database import WalletDatabase
from lbrynet.wallet.dewies import dewies_to_lbc


log = logging.getLogger(__name__)


class LbryWalletManager(BaseWalletManager):

    @property
    def ledger(self) -> MainNetLedger:
        return self.default_account.ledger

    @property
    def db(self) -> WalletDatabase:
        return self.ledger.db

    @property
    def use_encryption(self):
        return self.default_account.serialize_encrypted

    @property
    def is_wallet_unlocked(self):
        return not self.default_account.encrypted

    def check_locked(self):
        return self.default_account.encrypted

    def decrypt_account(self, account):
        assert account.password is not None, "account is not unlocked"
        assert not account.encrypted, "account is not unlocked"
        account.serialize_encrypted = False
        self.save()
        return not account.encrypted and not account.serialize_encrypted

    def encrypt_account(self, password, account):
        assert not account.encrypted, "account is already encrypted"
        account.encrypt(password)
        account.serialize_encrypted = True
        self.save()
        self.unlock_account(password, account)
        return account.serialize_encrypted

    def unlock_account(self, password, account):
        assert account.encrypted, "account is not locked"
        account.decrypt(password)
        return not account.encrypted

    def lock_account(self, account):
        assert account.password is not None, "account is already locked"
        assert not account.encrypted and account.serialize_encrypted, "account is not encrypted"
        account.encrypt(account.password)
        return account.encrypted

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
    async def from_lbrynet_config(cls, settings):

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

        wallet_file_path = os.path.join(wallets_directory, 'default_wallet')

        receiving_addresses, change_addresses = cls.migrate_lbryum_to_torba(wallet_file_path)

        manager = cls.from_config({
            'ledgers': {ledger_id: ledger_config},
            'wallets': [wallet_file_path]
        })
        ledger = manager.get_or_create_ledger(ledger_id)
        if manager.default_account is None:
            log.info('Wallet at %s is empty, generating a default account.', wallet_file_path)
            manager.default_wallet.generate_account(ledger)
            manager.default_wallet.save()
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
                height = await self.ledger.network.get_transaction_height(txid)
            except CodeMessageError as e:
                return {'success': False, 'code': e.code, 'message': e.message}
            tx = self.ledger.transaction_class(unhexlify(raw))
            await self.ledger.maybe_verify_transaction(tx, height)
        return tx

    @staticmethod
    async def get_history(account: BaseAccount, **constraints):
        headers = account.ledger.headers
        txs = await account.get_transactions(**constraints)
        history = []
        for tx in txs:
            ts = headers[tx.height]['timestamp'] if tx.height > 0 else None
            item = {
                'txid': tx.id,
                'timestamp': ts,
                'date': datetime.fromtimestamp(ts).isoformat(' ')[:-3] if tx.height > 0 else None,
                'confirmations': (headers.height+1) - tx.height if tx.height > 0 else 0,
                'claim_info': [],
                'update_info': [],
                'support_info': [],
                'abandon_info': []
            }
            is_my_inputs = all([txi.is_my_account for txi in tx.inputs])
            if is_my_inputs:
                # fees only matter if we are the ones paying them
                item['value'] = dewies_to_lbc(tx.net_account_balance+tx.fee)
                item['fee'] = dewies_to_lbc(-tx.fee)
            else:
                # someone else paid the fees
                item['value'] = dewies_to_lbc(tx.net_account_balance)
                item['fee'] = '0.0'
            for txo in tx.my_claim_outputs:
                item['claim_info'].append({
                    'address': txo.get_address(account.ledger),
                    'balance_delta': dewies_to_lbc(-txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.claim_id,
                    'claim_name': txo.claim_name,
                    'nout': txo.position
                })
            for txo in tx.my_update_outputs:
                if is_my_inputs:  # updating my own claim
                    previous = None
                    for txi in tx.inputs:
                        if txi.txo_ref.txo is not None:
                            other_txo = txi.txo_ref.txo
                            if (other_txo.is_claim or other_txo.script.is_support_claim) \
                                    and other_txo.claim_id == txo.claim_id:
                                previous = other_txo
                                break
                    if previous is not None:
                        item['update_info'].append({
                            'address': txo.get_address(account.ledger),
                            'balance_delta': dewies_to_lbc(previous.amount-txo.amount),
                            'amount': dewies_to_lbc(txo.amount),
                            'claim_id': txo.claim_id,
                            'claim_name': txo.claim_name,
                            'nout': txo.position
                        })
                else:  # someone sent us their claim
                    item['update_info'].append({
                        'address': txo.get_address(account.ledger),
                        'balance_delta': dewies_to_lbc(0),
                        'amount': dewies_to_lbc(txo.amount),
                        'claim_id': txo.claim_id,
                        'claim_name': txo.claim_name,
                        'nout': txo.position
                    })
            for txo in tx.my_support_outputs:
                item['support_info'].append({
                    'address': txo.get_address(account.ledger),
                    'balance_delta': dewies_to_lbc(txo.amount if not is_my_inputs else -txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.claim_id,
                    'claim_name': txo.claim_name,
                    'is_tip': not is_my_inputs,
                    'nout': txo.position
                })
            if is_my_inputs:
                for txo in tx.other_support_outputs:
                    item['support_info'].append({
                        'address': txo.get_address(account.ledger),
                        'balance_delta': dewies_to_lbc(-txo.amount),
                        'amount': dewies_to_lbc(txo.amount),
                        'claim_id': txo.claim_id,
                        'claim_name': txo.claim_name,
                        'is_tip': is_my_inputs,
                        'nout': txo.position
                    })
            for txo in tx.my_abandon_outputs:
                item['abandon_info'].append({
                    'address': txo.get_address(account.ledger),
                    'balance_delta': dewies_to_lbc(txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.claim_id,
                    'claim_name': txo.claim_name,
                    'nout': txo.position
                })
            history.append(item)
        return history

    def save(self):
        for wallet in self.wallets:
            wallet.save()
