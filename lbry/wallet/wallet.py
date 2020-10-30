# pylint: disable=arguments-differ
import json
import zlib
import asyncio
import logging
from datetime import datetime
from typing import Awaitable, Callable, List, Tuple, Optional, Iterable, Union
from hashlib import sha256
from operator import attrgetter
from decimal import Decimal

from lbry.db import Database, SPENDABLE_TYPE_CODES, Result
from lbry.event import EventController
from lbry.constants import COIN, NULL_HASH32
from lbry.blockchain.transaction import Transaction, Input, Output
from lbry.blockchain.dewies import dewies_to_lbc
from lbry.crypto.crypt import better_aes_encrypt, better_aes_decrypt
from lbry.crypto.bip32 import PubKey, PrivateKey
from lbry.schema.claim import Claim
from lbry.schema.purchase import Purchase
from lbry.error import InsufficientFundsError, KeyFeeAboveMaxAllowedError
from lbry.stream.managed_stream import ManagedStream

from .account import Account
from .coinselection import CoinSelector, OutputEffectiveAmountEstimator
from .preferences import TimestampedPreferences


log = logging.getLogger(__name__)

ENCRYPT_ON_DISK = 'encrypt-on-disk'


class Wallet:
    """ The primary role of Wallet is to encapsulate a collection
        of accounts (seed/private keys) and the spending rules / settings
        for the coins attached to those accounts.
    """

    VERSION = 1

    def __init__(self, wallet_id: str, db: Database, name: str = "", preferences: dict = None):
        self.id = wallet_id
        self.db = db
        self.name = name
        self.ledger = db.ledger
        self.preferences = TimestampedPreferences(preferences or {})
        self.encryption_password: Optional[str] = None

        self.utxo_lock = asyncio.Lock()
        self._on_change_controller = EventController()
        self.on_change = self._on_change_controller.stream

        self.accounts = AccountListManager(self)
        self.claims = ClaimListManager(self)
        self.streams = StreamListManager(self)
        self.channels = ChannelListManager(self)
        self.collections = CollectionListManager(self)
        self.purchases = PurchaseListManager(self)
        self.supports = SupportListManager(self)

    async def generate_addresses(self):
        await asyncio.wait([
            account.ensure_address_gap()
            for account in self.accounts
        ])

    async def notify_change(self, field: str, value=None):
        await self._on_change_controller.add({
            'field': field, 'value': value
        })

    @classmethod
    async def from_dict(cls, wallet_id: str, wallet_dict, db: Database) -> 'Wallet':
        if 'ledger' in wallet_dict and wallet_dict['ledger'] != db.ledger.get_id():
            raise ValueError(
                f"Using ledger {db.ledger.get_id()} but wallet is {wallet_dict['ledger']}."
            )
        version = wallet_dict.get('version')
        if version == 1:
            pass
        wallet = cls(
            wallet_id, db,
            name=wallet_dict.get('name', 'Wallet'),
            preferences=wallet_dict.get('preferences', {}),
        )
        for account_dict in wallet_dict.get('accounts', []):
            await wallet.accounts.add_from_dict(account_dict)
        return wallet

    def to_dict(self, encrypt_password: str = None) -> dict:
        return {
            'version': self.VERSION,
            'ledger': self.ledger.get_id(),
            'name': self.name,
            'preferences': self.preferences.data,
            'accounts': [a.to_dict(encrypt_password) for a in self.accounts]
        }

    @classmethod
    async def from_serialized(cls, wallet_id: str, json_data: str, db: Database) -> 'Wallet':
        return await cls.from_dict(wallet_id, json.loads(json_data), db)

    def to_serialized(self) -> str:
        wallet_dict = None
        if self.preferences.get(ENCRYPT_ON_DISK, False):
            if self.encryption_password is not None:
                wallet_dict = self.to_dict(encrypt_password=self.encryption_password)
            elif not self.is_locked:
                log.warning(
                    "Disk encryption requested but no password available for encryption. "
                    "Saving wallet in an unencrypted state."
                )
        if wallet_dict is None:
            wallet_dict = self.to_dict()
        return json.dumps(wallet_dict, indent=4, sort_keys=True)

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

    async def merge(self, password: str, data: str) -> List[Account]:
        assert not self.is_locked, "Cannot sync apply on a locked wallet."
        added_accounts = []
        decrypted_data = self.unpack(password, data)
        self.preferences.merge(decrypted_data.get('preferences', {}))
        for account_dict in decrypted_data['accounts']:
            _, _, pubkey = await Account.keys_from_dict(self.ledger, account_dict)
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
                    await self.accounts.add_from_dict(account_dict, notify=False)
                )
        await self.notify_change('wallet.merge')
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

    async def decrypt(self):
        assert not self.is_locked, "Cannot decrypt a locked wallet, unlock first."
        self.preferences[ENCRYPT_ON_DISK] = False
        await self.notify_change(ENCRYPT_ON_DISK, False)
        return True

    async def encrypt(self, password):
        assert not self.is_locked, "Cannot re-encrypt a locked wallet, unlock first."
        assert password, "Cannot encrypt with blank password."
        self.encryption_password = password
        self.preferences[ENCRYPT_ON_DISK] = True
        await self.notify_change(ENCRYPT_ON_DISK, True)
        return True

    @property
    def has_accounts(self):
        return len(self.accounts) > 0

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
            await self.notify_change('address-max-gap')

    async def get_effective_amount_estimators(self, funding_accounts: Iterable[Account]):
        estimators = []
        utxos = await self.db.get_utxos(
            accounts=funding_accounts,
            txo_type__in=SPENDABLE_TYPE_CODES
        )
        for utxo in utxos:
            estimators.append(OutputEffectiveAmountEstimator(self.ledger, utxo))
        return estimators

    async def get_spendable_utxos(self, amount: int, funding_accounts: Iterable[Account]):
        async with self.utxo_lock:
            txos = await self.get_effective_amount_estimators(funding_accounts)
            fee = Output.pay_pubkey_hash(COIN, NULL_HASH32).get_fee(self.ledger)
            selector = CoinSelector(amount, fee)
            spendables = selector.select(txos, self.ledger.coin_selection_strategy)
            if spendables:
                await self.db.reserve_outputs(s.txo for s in spendables)
            return spendables

    async def list_transactions(self, **constraints):
        return txs_to_dict(await self.db.get_transactions(
            include_is_my_output=True, **constraints
        ), self.ledger)

    async def create_transaction(
            self, inputs: Iterable[Input], outputs: Iterable[Output],
            funding_accounts: Iterable[Account], change_account: Account):
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

        except Exception as e:
            await self.db.release_tx(tx)
            raise e

        return tx

    async def sign(self, tx):
        for i, txi in enumerate(tx._inputs):
            assert txi.script is not None
            assert txi.txo_ref.txo is not None
            txo_script = txi.txo_ref.txo.script
            if txo_script.is_pay_pubkey_hash:
                address = self.ledger.pubkey_hash_to_address(txo_script.values['pubkey_hash'])
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

    async def pay(self, amount: int, address: bytes, funding_accounts: List[Account], change_account: Account):
        output = Output.pay_pubkey_hash(amount, self.ledger.address_to_hash160(address))
        return await self.create_transaction([], [output], funding_accounts, change_account)

    async def fund(self, from_account, to_account, amount=None, everything=False,
                   outputs=1, broadcast=False, **constraints):
        assert self.ledger == to_account.ledger, 'Can only transfer between accounts of the same ledger.'
        if everything:
            utxos = await self.db.get_utxos(**constraints)
            await self.db.reserve_outputs(utxos)
            tx = await self.create_transaction(
                inputs=[Input.spend(txo) for txo in utxos],
                outputs=[],
                funding_accounts=[from_account],
                change_account=to_account
            )
        elif amount > 0:
            to_address = await to_account.change.get_or_create_usable_address()
            to_hash160 = to_account.ledger.address_to_hash160(to_address)
            tx = await self.create_transaction(
                inputs=[],
                outputs=[
                    Output.pay_pubkey_hash(amount//outputs, to_hash160)
                    for _ in range(outputs)
                ],
                funding_accounts=[from_account],
                change_account=from_account
            )
        else:
            raise ValueError('An amount is required.')

        return tx

    async def verify_duplicate(self, name: str, allow_duplicate: bool):
        if not allow_duplicate:
            claims = await self.claims.list(claim_name=name)
            if len(claims) > 0:
                raise Exception(
                    f"You already have a claim published under the name '{name}'. "
                    f"Use --allow-duplicate-name flag to override."
                )

    async def get_balance(self, **constraints):
        return await self.db.get_balance(accounts=self.accounts, **constraints)


class AccountListManager:
    __slots__ = 'wallet', '_accounts'

    def __init__(self, wallet: Wallet):
        self.wallet = wallet
        self._accounts: List[Account] = []

    def __len__(self):
        return self._accounts.__len__()

    def __iter__(self):
        return self._accounts.__iter__()

    def __getitem__(self, account_id: str) -> Account:
        for account in self:
            if account.id == account_id:
                return account
        raise ValueError(f"Couldn't find account: {account_id}.")

    @property
    def default(self) -> Optional[Account]:
        for account in self:
            return account

    async def generate(self, name: str = None, language: str = 'en', address_generator: dict = None) -> Account:
        account = await Account.generate(self.wallet.db, name, language, address_generator)
        self._accounts.append(account)
        await self.wallet.notify_change('account.added')
        return account

    async def add_from_dict(self, account_dict: dict, notify=True) -> Account:
        account = await Account.from_dict(self.wallet.db, account_dict)
        self._accounts.append(account)
        if notify:
            await self.wallet.notify_change('account.added')
        return account

    async def remove(self, account_id: str) -> Account:
        account = self[account_id]
        self._accounts.remove(account)
        await self.wallet.notify_change('account.removed')
        return account

    def set_default(self, account):
        self._accounts.remove(account)
        self._accounts.insert(0, account)

    def get_or_none(self, account_id: str) -> Optional[Account]:
        if account_id is not None:
            return self[account_id]

    def get_or_default(self, account_id: str) -> Optional[Account]:
        if account_id is None:
            return self.default
        return self[account_id]

    def get_or_all(self, account_ids: Union[List[str], str]) -> List[Account]:
        if account_ids and isinstance(account_ids, str):
            account_ids = [account_ids]
        return [self[account_id] for account_id in account_ids] if account_ids else self._accounts

    async def get_account_details(self, **kwargs):
        accounts = []
        for i, account in enumerate(self._accounts):
            details = await account.get_details(**kwargs)
            details['is_default'] = i == 0
            accounts.append(details)
        return accounts


class BaseListManager:
    __slots__ = 'wallet',

    def __init__(self, wallet: Wallet):
        self.wallet = wallet

    async def create(self, *args, **kwargs) -> Transaction:
        raise NotImplementedError

    async def delete(self, **constraints) -> Transaction:
        raise NotImplementedError

    async def list(self, **constraints) -> Tuple[List[Output], Optional[int]]:
        raise NotImplementedError

    async def get(self, **constraints) -> Output:
        raise NotImplementedError

    async def get_or_none(self, **constraints) -> Optional[Output]:
        raise NotImplementedError


class ClaimListManager(BaseListManager):
    name = 'claim'
    __slots__ = ()

    async def _create(
            self, name: str, claim: Claim, amount: int, holding_address: str,
            funding_accounts: List[Account], change_account: Account,
            signing_channel: Output = None) -> Transaction:
        txo = Output.pay_claim_name_pubkey_hash(
            amount, name, claim, self.wallet.ledger.address_to_hash160(holding_address)
        )
        if signing_channel is not None:
            txo.sign(signing_channel, b'placeholder txid:nout')
        tx = await self.wallet.create_transaction(
            [], [txo], funding_accounts, change_account
        )
        return tx

    async def create(
            self, name: str, claim: Claim, amount: int, holding_address: str,
            funding_accounts: List[Account], change_account: Account,
            signing_channel: Output = None) -> Transaction:
        tx = await self._create(
            name, claim, amount, holding_address,
            funding_accounts, change_account,
            signing_channel
        )
        txo = tx.outputs[0]
        if signing_channel is not None:
            txo.sign(signing_channel)
        await self.wallet.sign(tx)
        return tx

    async def update(
            self, previous_claim: Output, claim: Claim, amount: int, holding_address: str,
            funding_accounts: List[Account], change_account: Account,
            signing_channel: Output = None) -> Transaction:
        updated_claim = Output.pay_update_claim_pubkey_hash(
            amount, previous_claim.claim_name, previous_claim.claim_id,
            claim, self.wallet.ledger.address_to_hash160(holding_address)
        )
        if signing_channel is not None:
            updated_claim.sign(signing_channel, b'placeholder txid:nout')
        else:
            updated_claim.clear_signature()
        return await self.wallet.create_transaction(
            [Input.spend(previous_claim)], [updated_claim], funding_accounts, change_account
        )

    async def delete(self, claim_id=None, txid=None, nout=None):
        claim = await self.get(claim_id=claim_id, txid=txid, nout=nout)
        return await self.wallet.create_transaction(
            [Input.spend(claim)], [], self.wallet._accounts, self.wallet._accounts[0]
        )

    async def list(self, **constraints) -> Result[Output]:
        return await self.wallet.db.get_claims(wallet=self.wallet, **constraints)

    async def get(self, claim_id=None, claim_name=None, txid=None, nout=None) -> Output:
        if txid is not None and nout is not None:
            key, value, constraints = 'txid:nout', f'{txid}:{nout}', {'tx_hash': '', 'position': nout}
        elif claim_id is not None:
            key, value, constraints = 'id', claim_id, {'claim_id': claim_id}
        elif claim_name is not None:
            key, value, constraints = 'name', claim_name, {'claim_name': claim_name}
        else:
            raise ValueError(f"Couldn't find {self.name} because an {self.name}_id or name was not provided.")
        claims = await self.list(is_spent=False, **constraints)
        if len(claims) == 1:
            return claims[0]
        elif len(claims) > 1:
            raise ValueError(
                f"Multiple {self.name}s found with {key} '{value}', "
                f"pass a {self.name}_id to narrow it down."
            )
        raise ValueError(f"Couldn't find {self.name} with {key} '{value}'.")

    async def get_or_none(self, claim_id=None, claim_name=None, txid=None, nout=None) -> Optional[Output]:
        if any((claim_id, claim_name, all((txid, nout)))):
            return await self.get(claim_id, claim_name, txid, nout)


class ChannelListManager(ClaimListManager):
    name = 'channel'
    __slots__ = ()

    async def create(
        self, name: str, amount: int, holding_account: Account,
        funding_accounts: List[Account], save_key=True, **kwargs
    ) -> Transaction:

        holding_address = await holding_account.receiving.get_or_create_usable_address()

        claim = Claim()
        claim.channel.update(**kwargs)
        txo = Output.pay_claim_name_pubkey_hash(
            amount, name, claim, self.wallet.ledger.address_to_hash160(holding_address)
        )

        await txo.generate_channel_private_key()

        tx = await self.wallet.create_transaction(
            [], [txo], funding_accounts, funding_accounts[0]
        )

        await self.wallet.sign(tx)

        if save_key:
            holding_account.add_channel_private_key(txo.private_key)
            await self.wallet.notify_change('channel.added')

        return tx

    async def update(
        self, old: Output, amount: int, new_signing_key: bool, replace: bool,
        holding_account: Account, funding_accounts: List[Account],
        save_key=True, **kwargs
    ) -> Transaction:

        moving_accounts = False
        holding_address = old.get_address(self.wallet.ledger)
        if holding_account:
            old_account = await self.wallet.get_account_for_address(holding_address)
            if holding_account.id != old_account.id:
                holding_address = await holding_account.receiving.get_or_create_usable_address()
                moving_accounts = True
        elif new_signing_key:
            holding_account = await self.wallet.get_account_for_address(holding_address)

        if replace:
            claim = Claim()
            claim.channel.public_key_bytes = old.claim.channel.public_key_bytes
        else:
            claim = Claim.from_bytes(old.claim.to_bytes())
        claim.channel.update(**kwargs)

        txo = Output.pay_update_claim_pubkey_hash(
            amount, old.claim_name, old.claim_id, claim,
            self.wallet.ledger.address_to_hash160(holding_address)
        )

        if new_signing_key:
            await txo.generate_channel_private_key()
        else:
            txo.private_key = old.private_key

        tx = await self.wallet.create_transaction(
            [Input.spend(old)], [txo], funding_accounts, funding_accounts[0]
        )

        await self.wallet.sign(tx)

        if any((new_signing_key, moving_accounts)) and save_key:
            holding_account.add_channel_private_key(txo.private_key)
            await self.wallet.notify_change('channel.added')

        return tx

    async def list(self, **constraints) -> Result[Output]:
        return await self.wallet.db.get_channels(wallet=self.wallet, **constraints)

    async def get_for_signing(self, channel_id=None, channel_name=None) -> Output:
        channel = await self.get(claim_id=channel_id, claim_name=channel_name)
        if not channel.has_private_key:
            raise Exception(
                f"Couldn't find private key for channel '{channel.claim_name}', "
                f"can't use channel for signing. "
            )
        return channel

    async def get_for_signing_or_none(self, channel_id=None, channel_name=None) -> Optional[Output]:
        if channel_id or channel_name:
            return await self.get_for_signing(channel_id, channel_name)


class StreamListManager(ClaimListManager):
    __slots__ = ()

    async def create(
        self, name: str, amount: int, file_path: str,
        create_file_stream: Callable[[str], Awaitable[ManagedStream]],
        holding_address: str, funding_accounts: List[Account], change_account: Account,
        signing_channel: Optional[Output] = None, preview=False, **kwargs
    ) -> Tuple[Transaction, ManagedStream]:

        claim = Claim()
        claim.stream.update(file_path=file_path, sd_hash='0' * 96, **kwargs)

        # before creating file stream, create TX to ensure we have enough LBC
        tx = await self._create(
            name, claim, amount, holding_address,
            funding_accounts, change_account,
            signing_channel
        )
        txo = tx.outputs[0]

        file_stream = None
        try:

            # we have enough LBC to create TX, now try create the file stream
            if not preview:
                file_stream = await create_file_stream(file_path)
                claim.stream.source.sd_hash = file_stream.sd_hash
                txo.script.generate()

            # creating TX and file stream was successful, now sign all the things
            if signing_channel is not None:
                txo.sign(signing_channel)
            await self.wallet.sign(tx)

        except Exception as e:
            # creating file stream or something else went wrong, release txos
            await self.wallet.db.release_tx(tx)
            raise e

        return tx, file_stream

    async def update(
        self, old: Output, amount: int, file_path: str,
        create_file_stream: Callable[[str], Awaitable[ManagedStream]],
        holding_address: str, funding_accounts: List[Account], change_account: Account,
        signing_channel: Optional[Output] = None,
        preview=False, replace=False, **kwargs
    ) -> Tuple[Transaction, ManagedStream]:

        if replace:
            claim = Claim()
            # stream file metadata is not replaced
            claim.stream.message.source.CopyFrom(old.claim.stream.message.source)
            stream_type = old.claim.stream.stream_type
            if stream_type:
                old_stream_type = getattr(old.claim.stream.message, stream_type)
                new_stream_type = getattr(claim.stream.message, stream_type)
                new_stream_type.CopyFrom(old_stream_type)
        else:
            claim = Claim.from_bytes(old.claim.to_bytes())
        claim.stream.update(file_path=file_path, **kwargs)

        # before creating file stream, create TX to ensure we have enough LBC
        tx = await super().update(
            old, claim, amount, holding_address,
            funding_accounts, change_account,
            signing_channel
        )
        txo = tx.outputs[0]

        file_stream = None
        try:

            # we have enough LBC to create TX, now try create the file stream
            if not preview:
                old_stream = None  # TODO: get old stream
                if file_path is not None:
                    if old_stream is not None:
                        # TODO: delete the old stream
                        pass
                    file_stream = await create_file_stream(file_path)
                    claim.stream.source.sd_hash = file_stream.sd_hash
                    txo.script.generate()

            # creating TX and file stream was successful, now sign all the things
            if signing_channel is not None:
                txo.sign(signing_channel)
            await self.wallet.sign(tx)

        except Exception as e:
            # creating file stream or something else went wrong, release txos
            await self.wallet.db.release_tx(tx)
            raise e

        return tx, file_stream

    async def list(self, **constraints) -> Result[Output]:
        return await self.wallet.db.get_streams(wallet=self.wallet, **constraints)


class CollectionListManager(ClaimListManager):
    __slots__ = ()

    async def create(
            self, name: str, amount: int, holding_address: str, funding_accounts: List[Account],
            channel: Optional[Output] = None, **kwargs) -> Transaction:
        claim = Claim()
        claim.collection.update(**kwargs)
        return await super().create(
            name, claim, amount, holding_address, funding_accounts, funding_accounts[0], channel
        )

    async def list(self, **constraints) -> Result[Output]:
        return await self.wallet.db.get_collections(wallet=self.wallet, **constraints)


class SupportListManager(BaseListManager):
    __slots__ = ()

    async def create(self, name: str, claim_id: str, amount: int, holding_address: str,
                     funding_accounts: List[Account], change_account: Account) -> Transaction:
        support_output = Output.pay_support_pubkey_hash(
            amount, name, claim_id, self.wallet.ledger.address_to_hash160(holding_address)
        )
        tx = await self.wallet.create_transaction(
            [], [support_output], funding_accounts, change_account
        )
        await self.wallet.sign(tx)
        return tx

    async def delete(self, supports, keep=0, funding_accounts=None, change_account=None):
        outputs = []
        if keep > 0:
            outputs = [
                Output.pay_support_pubkey_hash(
                    keep, supports[0].claim_name, supports[0].claim_id, supports[0].pubkey_hash
                )
            ]
        tx = await self.wallet.create_transaction(
            [Input.spend(txo) for txo in supports], outputs,
            funding_accounts or self.wallet._accounts,
            change_account or self.wallet._accounts[0]
        )
        await self.wallet.sign(tx)
        return tx

    async def list(self, **constraints) -> Result[Output]:
        return await self.wallet.db.get_supports(**constraints)

    async def get(self, **constraints) -> Output:
        raise NotImplementedError

    async def get_or_none(self, **constraints) -> Optional[Output]:
        raise NotImplementedError


class PurchaseListManager(BaseListManager):
    __slots__ = ()

    async def create(self, name: str, claim_id: str, amount: int, holding_address: str,
                     funding_accounts: List[Account], change_account: Account) -> Transaction:
        support_output = Output.pay_support_pubkey_hash(
            amount, name, claim_id, self.wallet.ledger.address_to_hash160(holding_address)
        )
        return await self.wallet.create_transaction(
            [], [support_output], funding_accounts, change_account
        )

    def purchase(self, claim_id: str, amount: int, merchant_address: bytes,
                 funding_accounts: List['Account'], change_account: 'Account'):
        payment = Output.pay_pubkey_hash(amount, self.wallet.ledger.address_to_hash160(merchant_address))
        data = Output.add_purchase_data(Purchase(claim_id))
        return self.wallet.create_transaction(
            [], [payment, data], funding_accounts, change_account
        )

    async def create_purchase_transaction(
            self, accounts: List[Account], txo: Output, exchange: 'ExchangeRateManager',
            override_max_key_fee=False):
        fee = txo.claim.stream.fee
        fee_amount = exchange.to_dewies(fee.currency, fee.amount)
        if not override_max_key_fee and self.wallet.ledger.conf.max_key_fee:
            max_fee = self.wallet.ledger.conf.max_key_fee
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
        fee_address = fee.address or txo.get_address(self.wallet.ledger)
        return await self.purchase(
            txo.claim_id, fee_amount, fee_address, accounts, accounts[0]
        )

    async def list(self, **constraints) -> Result[Output]:
        return await self.wallet.db.get_purchases(**constraints)

    async def get(self, **constraints) -> Output:
        raise NotImplementedError

    async def get_or_none(self, **constraints) -> Optional[Output]:
        raise NotImplementedError


def txs_to_dict(txs, ledger):
    history = []
    for tx in txs:  # pylint: disable=too-many-nested-blocks
        ts = ledger.headers.estimated_timestamp(tx.height)
        item = {
            'txid': tx.id,
            'timestamp': ts,
            'date': datetime.fromtimestamp(ts).isoformat(' ')[:-3] if tx.height > 0 else None,
            'confirmations': (ledger.headers.height + 1) - tx.height if tx.height > 0 else 0,
            'claim_info': [],
            'update_info': [],
            'support_info': [],
            'abandon_info': [],
            'purchase_info': []
        }
        is_my_inputs = all([txi.is_my_input for txi in tx.inputs])
        if is_my_inputs:
            # fees only matter if we are the ones paying them
            item['value'] = dewies_to_lbc(tx.net_account_balance + tx.fee)
            item['fee'] = dewies_to_lbc(-tx.fee)
        else:
            # someone else paid the fees
            item['value'] = dewies_to_lbc(tx.net_account_balance)
            item['fee'] = '0.0'
        for txo in tx.my_claim_outputs:
            item['claim_info'].append({
                'address': txo.get_address(ledger),
                'balance_delta': dewies_to_lbc(-txo.amount),
                'amount': dewies_to_lbc(txo.amount),
                'claim_id': txo.claim_id,
                'claim_name': txo.claim_name,
                'nout': txo.position,
                'is_spent': txo.is_spent,
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
                        'address': txo.get_address(ledger),
                        'balance_delta': dewies_to_lbc(previous.amount - txo.amount),
                        'amount': dewies_to_lbc(txo.amount),
                        'claim_id': txo.claim_id,
                        'claim_name': txo.claim_name,
                        'nout': txo.position,
                        'is_spent': txo.is_spent,
                    })
            else:  # someone sent us their claim
                item['update_info'].append({
                    'address': txo.get_address(ledger),
                    'balance_delta': dewies_to_lbc(0),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.claim_id,
                    'claim_name': txo.claim_name,
                    'nout': txo.position,
                    'is_spent': txo.is_spent,
                })
        for txo in tx.my_support_outputs:
            item['support_info'].append({
                'address': txo.get_address(ledger),
                'balance_delta': dewies_to_lbc(txo.amount if not is_my_inputs else -txo.amount),
                'amount': dewies_to_lbc(txo.amount),
                'claim_id': txo.claim_id,
                'claim_name': txo.claim_name,
                'is_tip': not is_my_inputs,
                'nout': txo.position,
                'is_spent': txo.is_spent,
            })
        if is_my_inputs:
            for txo in tx.other_support_outputs:
                item['support_info'].append({
                    'address': txo.get_address(ledger),
                    'balance_delta': dewies_to_lbc(-txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.claim_id,
                    'claim_name': txo.claim_name,
                    'is_tip': is_my_inputs,
                    'nout': txo.position,
                    'is_spent': txo.is_spent,
                })
        for txo in tx.my_abandon_outputs:
            item['abandon_info'].append({
                'address': txo.get_address(ledger),
                'balance_delta': dewies_to_lbc(txo.amount),
                'amount': dewies_to_lbc(txo.amount),
                'claim_id': txo.claim_id,
                'claim_name': txo.claim_name,
                'nout': txo.position
            })
        for txo in tx.any_purchase_outputs:
            item['purchase_info'].append({
                'address': txo.get_address(ledger),
                'balance_delta': dewies_to_lbc(txo.amount if not is_my_inputs else -txo.amount),
                'amount': dewies_to_lbc(txo.amount),
                'claim_id': txo.purchased_claim_id,
                'nout': txo.position,
                'is_spent': txo.is_spent,
            })
        history.append(item)
    return history
