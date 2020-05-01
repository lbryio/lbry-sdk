import os
import time
import stat
import json
import zlib
import typing
import logging
from typing import List, Sequence, MutableSequence, Optional, Iterable
from collections import UserDict
from hashlib import sha256
from operator import attrgetter
from decimal import Decimal

from lbry.db import Database
from lbry.blockchain.ledger import Ledger
from lbry.constants import COIN, NULL_HASH32
from lbry.blockchain.transaction import Transaction, Input, Output
from lbry.blockchain.dewies import dewies_to_lbc
from lbry.crypto.crypt import better_aes_encrypt, better_aes_decrypt
from lbry.crypto.bip32 import PubKey, PrivateKey
from lbry.schema.claim import Claim
from lbry.schema.purchase import Purchase
from lbry.error import InsufficientFundsError, KeyFeeAboveMaxAllowedError

from .account import Account
from .coinselection import CoinSelector, OutputEffectiveAmountEstimator

if typing.TYPE_CHECKING:
    from lbry.extras.daemon.exchange_rate_manager import ExchangeRateManager


log = logging.getLogger(__name__)

ENCRYPT_ON_DISK = 'encrypt-on-disk'


class TimestampedPreferences(UserDict):

    def __init__(self, d: dict = None):
        super().__init__()
        if d is not None:
            self.data = d.copy()

    def __getitem__(self, key):
        return self.data[key]['value']

    def __setitem__(self, key, value):
        self.data[key] = {
            'value': value,
            'ts': time.time()
        }

    def __repr__(self):
        return repr(self.to_dict_without_ts())

    def to_dict_without_ts(self):
        return {
            key: value['value'] for key, value in self.data.items()
        }

    @property
    def hash(self):
        return sha256(json.dumps(self.data).encode()).digest()

    def merge(self, other: dict):
        for key, value in other.items():
            if key in self.data and value['ts'] < self.data[key]['ts']:
                continue
            self.data[key] = value


class Wallet:
    """ The primary role of Wallet is to encapsulate a collection
        of accounts (seed/private keys) and the spending rules / settings
        for the coins attached to those accounts. Wallets are represented
        by physical files on the filesystem.
    """

    preferences: TimestampedPreferences
    encryption_password: Optional[str]

    def __init__(self, ledger: Ledger, db: Database,
                 name: str = 'Wallet', accounts: MutableSequence[Account] = None,
                 storage: 'WalletStorage' = None, preferences: dict = None) -> None:
        self.ledger = ledger
        self.db = db
        self.name = name
        self.accounts = accounts or []
        self.storage = storage or WalletStorage()
        self.preferences = TimestampedPreferences(preferences or {})
        self.encryption_password = None
        self.id = self.get_id()

    def get_id(self):
        return os.path.basename(self.storage.path) if self.storage.path else self.name

    def generate_account(self, name: str = None, address_generator: dict = None) -> Account:
        account = Account.generate(self.ledger, self.db, name, address_generator)
        self.accounts.append(account)
        return account

    def add_account(self, account_dict) -> Account:
        account = Account.from_dict(self.ledger, self.db, account_dict)
        self.accounts.append(account)
        return account

    @property
    def default_account(self) -> Optional[Account]:
        for account in self.accounts:
            return account
        return None

    def get_account_or_default(self, account_id: str) -> Optional[Account]:
        if account_id is None:
            return self.default_account
        return self.get_account_or_error(account_id)

    def get_account_or_error(self, account_id: str) -> Account:
        for account in self.accounts:
            if account.id == account_id:
                return account
        raise ValueError(f"Couldn't find account: {account_id}.")

    def get_accounts_or_all(self, account_ids: List[str]) -> Sequence[Account]:
        return [
            self.get_account_or_error(account_id)
            for account_id in account_ids
        ] if account_ids else self.accounts

    async def get_detailed_accounts(self, **kwargs):
        accounts = []
        for i, account in enumerate(self.accounts):
            details = await account.get_details(**kwargs)
            details['is_default'] = i == 0
            accounts.append(details)
        return accounts

    async def _get_account_and_address_info_for_address(self, address):
        match = await self.db.get_address(accounts=self.accounts, address=address)
        if match:
            for account in self.accounts:
                if match['account'] == account.public_key.address:
                    return account, match

    async def get_private_key_for_address(self, address) -> Optional[PrivateKey]:
        match = await self._get_account_and_address_info_for_address(address)
        if match:
            account, address_info = match
            return account.get_private_key(address_info['chain'], address_info['pubkey'].n)
        return None

    async def get_public_key_for_address(self, address) -> Optional[PubKey]:
        match = await self._get_account_and_address_info_for_address(address)
        if match:
            _, address_info = match
            return address_info['pubkey']
        return None

    async def get_account_for_address(self, address):
        match = await self._get_account_and_address_info_for_address(address)
        if match:
            return match[0]

    async def save_max_gap(self):
        gap_changed = False
        for account in self.accounts:
            if await account.save_max_gap():
                gap_changed = True
        if gap_changed:
            self.save()

    @classmethod
    def from_storage(cls, ledger: Ledger, db: Database, storage: 'WalletStorage') -> 'Wallet':
        json_dict = storage.read()
        if 'ledger' in json_dict and json_dict['ledger'] != ledger.get_id():
            raise ValueError(
                f"Using ledger {ledger.get_id()} but wallet is {json_dict['ledger']}."
            )
        wallet = cls(
            ledger, db,
            name=json_dict.get('name', 'Wallet'),
            preferences=json_dict.get('preferences', {}),
            storage=storage
        )
        account_dicts: Sequence[dict] = json_dict.get('accounts', [])
        for account_dict in account_dicts:
            wallet.add_account(account_dict)
        return wallet

    def to_dict(self, encrypt_password: str = None):
        return {
            'version': WalletStorage.LATEST_VERSION,
            'name': self.name,
            'ledger': self.ledger.get_id(),
            'preferences': self.preferences.data,
            'accounts': [a.to_dict(encrypt_password) for a in self.accounts]
        }

    def save(self):
        if self.preferences.get(ENCRYPT_ON_DISK, False):
            if self.encryption_password is not None:
                return self.storage.write(self.to_dict(encrypt_password=self.encryption_password))
            elif not self.is_locked:
                log.warning(
                    "Disk encryption requested but no password available for encryption. "
                    "Saving wallet in an unencrypted state."
                )
        return self.storage.write(self.to_dict())

    @property
    def hash(self) -> bytes:
        h = sha256()
        if self.preferences.get(ENCRYPT_ON_DISK, False):
            assert self.encryption_password is not None, \
                "Encryption is enabled but no password is available, cannot generate hash."
            h.update(self.encryption_password.encode())
        h.update(self.preferences.hash)
        for account in sorted(self.accounts, key=attrgetter('id')):
            h.update(account.hash)
        return h.digest()

    def pack(self, password):
        assert not self.is_locked, "Cannot pack a wallet with locked/encrypted accounts."
        new_data = json.dumps(self.to_dict())
        new_data_compressed = zlib.compress(new_data.encode())
        return better_aes_encrypt(password, new_data_compressed)

    @classmethod
    def unpack(cls, password, encrypted):
        decrypted = better_aes_decrypt(password, encrypted)
        decompressed = zlib.decompress(decrypted)
        return json.loads(decompressed)

    def merge(self, password: str, data: str) -> List[Account]:
        assert not self.is_locked, "Cannot sync apply on a locked wallet."
        added_accounts = []
        decrypted_data = self.unpack(password, data)
        self.preferences.merge(decrypted_data.get('preferences', {}))
        for account_dict in decrypted_data['accounts']:
            _, _, pubkey = Account.keys_from_dict(self.ledger, account_dict)
            account_id = pubkey.address
            local_match = None
            for local_account in self.accounts:
                if account_id == local_account.id:
                    local_match = local_account
                    break
            if local_match is not None:
                local_match.merge(account_dict)
            else:
                added_accounts.append(
                    self.add_account(account_dict)
                )
        return added_accounts

    @property
    def is_locked(self) -> bool:
        for account in self.accounts:
            if account.encrypted:
                return True
        return False

    def unlock(self, password):
        for account in self.accounts:
            if account.encrypted:
                if not account.decrypt(password):
                    return False
        self.encryption_password = password
        return True

    def lock(self):
        assert self.encryption_password is not None, "Cannot lock an unencrypted wallet, encrypt first."
        for account in self.accounts:
            if not account.encrypted:
                account.encrypt(self.encryption_password)
        return True

    @property
    def is_encrypted(self) -> bool:
        return self.is_locked or self.preferences.get(ENCRYPT_ON_DISK, False)

    def decrypt(self):
        assert not self.is_locked, "Cannot decrypt a locked wallet, unlock first."
        self.preferences[ENCRYPT_ON_DISK] = False
        self.save()
        return True

    def encrypt(self, password):
        assert not self.is_locked, "Cannot re-encrypt a locked wallet, unlock first."
        assert password, "Cannot encrypt with blank password."
        self.encryption_password = password
        self.preferences[ENCRYPT_ON_DISK] = True
        self.save()
        return True

    async def get_effective_amount_estimators(self, funding_accounts: Iterable[Account]):
        estimators = []
        for utxo in (await self.db.get_utxos(accounts=funding_accounts))[0]:
            estimators.append(OutputEffectiveAmountEstimator(self.ledger, utxo))
        return estimators

    async def get_spendable_utxos(self, amount: int, funding_accounts: Iterable[Account]):
        txos = await self.get_effective_amount_estimators(funding_accounts)
        fee = Output.pay_pubkey_hash(COIN, NULL_HASH32).get_fee(self.ledger)
        selector = CoinSelector(amount, fee)
        spendables = selector.select(txos, self.ledger.coin_selection_strategy)
        if spendables:
            await self.db.reserve_outputs(s.txo for s in spendables)
        return spendables

    async def create_transaction(self, inputs: Iterable[Input], outputs: Iterable[Output],
                     funding_accounts: Iterable[Account], change_account: Account,
                     sign: bool = True):
        """ Find optimal set of inputs when only outputs are provided; add change
            outputs if only inputs are provided or if inputs are greater than outputs. """

        tx = Transaction() \
            .add_inputs(inputs) \
            .add_outputs(outputs)

        # value of the outputs plus associated fees
        cost = (
                tx.get_base_fee(self.ledger) +
                tx.get_total_output_sum(self.ledger)
        )
        # value of the inputs less the cost to spend those inputs
        payment = tx.get_effective_input_sum(self.ledger)

        try:

            for _ in range(5):

                if payment < cost:
                    deficit = cost - payment
                    spendables = await self.get_spendable_utxos(deficit, funding_accounts)
                    if not spendables:
                        raise InsufficientFundsError()
                    payment += sum(s.effective_amount for s in spendables)
                    tx.add_inputs(s.txi for s in spendables)

                cost_of_change = (
                        tx.get_base_fee(self.ledger) +
                        Output.pay_pubkey_hash(COIN, NULL_HASH32).get_fee(self.ledger)
                )
                if payment > cost:
                    change = payment - cost
                    if change > cost_of_change:
                        change_address = await change_account.change.get_or_create_usable_address()
                        change_hash160 = change_account.ledger.address_to_hash160(change_address)
                        change_amount = change - cost_of_change
                        change_output = Output.pay_pubkey_hash(change_amount, change_hash160)
                        change_output.is_internal_transfer = True
                        tx.add_outputs([Output.pay_pubkey_hash(change_amount, change_hash160)])

                if tx._outputs:
                    break
                # this condition and the outer range(5) loop cover an edge case
                # whereby a single input is just enough to cover the fee and
                # has some change left over, but the change left over is less
                # than the cost_of_change: thus the input is completely
                # consumed and no output is added, which is an invalid tx.
                # to be able to spend this input we must increase the cost
                # of the TX and run through the balance algorithm a second time
                # adding an extra input and change output, making tx valid.
                # we do this 5 times in case the other UTXOs added are also
                # less than the fee, after 5 attempts we give up and go home
                cost += cost_of_change + 1

            if sign:
                await self.sign(tx)

        except Exception as e:
            log.exception('Failed to create transaction:')
            await self.db.release_tx(tx)
            raise e

        return tx

    async def sign(self, tx):
        for i, txi in enumerate(tx._inputs):
            assert txi.script is not None
            assert txi.txo_ref.txo is not None
            txo_script = txi.txo_ref.txo.script
            if txo_script.is_pay_pubkey_hash:
                address = self.ledger.hash160_to_address(txo_script.values['pubkey_hash'])
                private_key = await self.get_private_key_for_address(address)
                assert private_key is not None, 'Cannot find private key for signing output.'
                serialized = tx._serialize_for_signature(i)
                txi.script.values['signature'] = \
                    private_key.sign(serialized) + bytes((tx.signature_hash_type(1),))
                txi.script.values['pubkey'] = private_key.public_key.pubkey_bytes
                txi.script.generate()
            else:
                raise NotImplementedError("Don't know how to spend this output.")
        tx._reset()

    @classmethod
    def pay(cls, amount: int, address: bytes, funding_accounts: List['Account'], change_account: 'Account'):
        output = Output.pay_pubkey_hash(amount, ledger.address_to_hash160(address))
        return cls.create([], [output], funding_accounts, change_account)

    def claim_create(
            self, name: str, claim: Claim, amount: int, holding_address: str,
            funding_accounts: List['Account'], change_account: 'Account', signing_channel: Output = None):
        claim_output = Output.pay_claim_name_pubkey_hash(
            amount, name, claim, self.ledger.address_to_hash160(holding_address)
        )
        if signing_channel is not None:
            claim_output.sign(signing_channel, b'placeholder txid:nout')
        return self.create_transaction(
            [], [claim_output], funding_accounts, change_account, sign=False
        )

    @classmethod
    def claim_update(
            cls, previous_claim: Output, claim: Claim, amount: int, holding_address: str,
            funding_accounts: List['Account'], change_account: 'Account', signing_channel: Output = None):
        updated_claim = Output.pay_update_claim_pubkey_hash(
            amount, previous_claim.claim_name, previous_claim.claim_id,
            claim, ledger.address_to_hash160(holding_address)
        )
        if signing_channel is not None:
            updated_claim.sign(signing_channel, b'placeholder txid:nout')
        else:
            updated_claim.clear_signature()
        return cls.create(
            [Input.spend(previous_claim)], [updated_claim], funding_accounts, change_account, sign=False
        )

    @classmethod
    def support(cls, claim_name: str, claim_id: str, amount: int, holding_address: str,
                funding_accounts: List['Account'], change_account: 'Account'):
        support_output = Output.pay_support_pubkey_hash(
            amount, claim_name, claim_id, ledger.address_to_hash160(holding_address)
        )
        return cls.create([], [support_output], funding_accounts, change_account)

    def purchase(self, claim_id: str, amount: int, merchant_address: bytes,
                 funding_accounts: List['Account'], change_account: 'Account'):
        payment = Output.pay_pubkey_hash(amount, self.ledger.address_to_hash160(merchant_address))
        data = Output.add_purchase_data(Purchase(claim_id))
        return self.create_transaction(
            [], [payment, data], funding_accounts, change_account
        )

    async def create_purchase_transaction(
            self, accounts: List[Account], txo: Output, exchange: 'ExchangeRateManager',
            override_max_key_fee=False):
        fee = txo.claim.stream.fee
        fee_amount = exchange.to_dewies(fee.currency, fee.amount)
        if not override_max_key_fee and self.ledger.conf.max_key_fee:
            max_fee = self.ledger.conf.max_key_fee
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
        return await self.purchase(
            txo.claim_id, fee_amount, fee_address, accounts, accounts[0]
        )

    async def create_channel(
            self, name, amount, account, funding_accounts,
            claim_address, preview=False, **kwargs):

        claim = Claim()
        claim.channel.update(**kwargs)
        tx = await self.claim_create(
            name, claim, amount, claim_address, funding_accounts, funding_accounts[0]
        )
        txo = tx.outputs[0]
        txo.generate_channel_private_key()

        await self.sign(tx)

        if not preview:
            account.add_channel_private_key(txo.private_key)
            self.save()

        return tx

    async def get_channels(self):
        return await self.db.get_channels()


class WalletStorage:

    LATEST_VERSION = 1

    def __init__(self, path=None, default=None):
        self.path = path
        self._default = default or {
            'version': self.LATEST_VERSION,
            'name': 'My Wallet',
            'preferences': {},
            'accounts': []
        }

    def read(self):
        if self.path and os.path.exists(self.path):
            with open(self.path, 'r') as f:
                json_data = f.read()
                json_dict = json.loads(json_data)
                if json_dict.get('version') == self.LATEST_VERSION and \
                        set(json_dict) == set(self._default):
                    return json_dict
                else:
                    return self.upgrade(json_dict)
        else:
            return self._default.copy()

    def upgrade(self, json_dict):
        json_dict = json_dict.copy()
        version = json_dict.pop('version', -1)
        if version == -1:
            pass
        upgraded = self._default.copy()
        upgraded.update(json_dict)
        return json_dict

    def write(self, json_dict):

        json_data = json.dumps(json_dict, indent=4, sort_keys=True)
        if self.path is None:
            return json_data

        temp_path = "{}.tmp.{}".format(self.path, os.getpid())
        with open(temp_path, "w") as f:
            f.write(json_data)
            f.flush()
            os.fsync(f.fileno())

        if os.path.exists(self.path):
            mode = os.stat(self.path).st_mode
        else:
            mode = stat.S_IREAD | stat.S_IWRITE
        try:
            os.rename(temp_path, self.path)
        except Exception:  # pylint: disable=broad-except
            os.remove(self.path)
            os.rename(temp_path, self.path)
        os.chmod(self.path, mode)
