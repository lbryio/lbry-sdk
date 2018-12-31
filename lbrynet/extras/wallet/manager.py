import os
import json
import logging
from binascii import unhexlify

from datetime import datetime
from typing import Optional

from twisted.internet import defer

from lbrynet.schema.schema import SECP256k1
from torba.client.basemanager import BaseWalletManager
from torba.rpc.jsonrpc import CodeMessageError

from lbrynet.schema.claim import ClaimDict

from lbrynet.extras.compat import f2d
from lbrynet.extras.wallet.ledger import MainNetLedger
from lbrynet.extras.wallet.account import BaseAccount, generate_certificate
from lbrynet.extras.wallet.transaction import Transaction
from lbrynet.extras.wallet.database import WalletDatabase
from lbrynet.extras.wallet.dewies import dewies_to_lbc


log = logging.getLogger(__name__)


class ReservedPoints:
    def __init__(self, identifier, amount):
        self.identifier = identifier
        self.amount = amount


class BackwardsCompatibleNetwork:
    def __init__(self, manager):
        self.manager = manager

    def get_local_height(self):
        for ledger in self.manager.ledgers.values():
            assert isinstance(ledger, MainNetLedger)
            return ledger.headers.height

    def get_server_height(self):
        return self.get_local_height()


class LbryWalletManager(BaseWalletManager):

    @property
    def ledger(self) -> MainNetLedger:
        return self.default_account.ledger

    @property
    def db(self) -> WalletDatabase:
        return self.ledger.db

    @property
    def wallet(self):
        return self

    @property
    def network(self):
        return BackwardsCompatibleNetwork(self)

    @property
    def use_encryption(self):
        return self.default_account.serialize_encrypted

    @property
    def is_first_run(self):
        return True

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
    async def from_lbrynet_config(cls, settings, db):

        ledger_id = {
            'lbrycrd_main':    'lbc_mainnet',
            'lbrycrd_testnet': 'lbc_testnet',
            'lbrycrd_regtest': 'lbc_regtest'
        }[settings['blockchain_name']]

        ledger_config = {
            'auto_connect': True,
            'default_servers': settings['lbryum_servers'],
            'data_path': settings.wallet_dir,
            'use_keyring': settings['use_keyring'],
            #'db': db
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

    def get_new_address(self):
        return self.get_unused_address()

    def reserve_points(self, address, amount: int):
        # TODO: check if we have enough to cover amount
        return ReservedPoints(address, amount)

    async def send_amount_to_address(self, amount: int, destination_address: bytes, account=None):
        account = account or self.default_account
        tx = await Transaction.pay(amount, destination_address, [account], account)
        await account.ledger.broadcast(tx)
        return tx

    async def send_claim_to_address(self, claim_id: str, destination_address: str, amount: Optional[int],
                              account=None):
        account = account or self.default_account
        claims = await account.get_claims(
            claim_name_type__any={'is_claim': 1, 'is_update': 1},  # exclude is_supports
            claim_id=claim_id
        )
        if not claims:
            raise NameError(f"Claim not found: {claim_id}")
        if not amount:
            amount = claims[0].get_estimator(self.ledger).effective_amount
        tx = await Transaction.update(
            claims[0], ClaimDict.deserialize(claims[0].script.values['claim']), amount,
            destination_address.encode(), [account], account
        )
        await self.ledger.broadcast(tx)
        return tx

    def send_points_to_address(self, reserved: ReservedPoints, amount: int, account=None):
        destination_address: bytes = reserved.identifier.encode('latin1')
        return self.send_amount_to_address(amount, destination_address, account)

    def get_wallet_info_query_handler_factory(self):
        return LBRYcrdAddressQueryHandlerFactory(self)

    def get_info_exchanger(self):
        return LBRYcrdAddressRequester(self)

    async def resolve(self, *uris, **kwargs):
        page = kwargs.get('page', 0)
        page_size = kwargs.get('page_size', 10)
        check_cache = kwargs.get('check_cache', False)  # TODO: put caching back (was force_refresh parameter)
        ledger: MainNetLedger = self.default_account.ledger
        results = await ledger.resolve(page, page_size, *uris)
        if 'error' not in results:
            await self.old_db.save_claims_for_resolve([
                value for value in results.values() if 'error' not in value
            ])
        return results

    async def get_claims_for_name(self, name: str):
        response = await self.ledger.network.get_claims_for_name(name)
        if 'claims' in response:
            to_resolve = [(claim['name'] + '#' + claim['claim_id']) for claim in response['claims']]
            response['claims'] = [resolution['claim'] for resolution in (await self.resolve(*to_resolve)).values()]
        return response

    async def address_is_mine(self, unknown_address, account):
        match = await self.ledger.db.get_address(address=unknown_address, account=account)
        if match is not None:
            return True
        return False

    async def get_transaction(self, txid):
        tx = await self.db.get_transaction(txid=txid)
        if not tx:
            try:
                _raw = await self.ledger.network.get_transaction(txid)
            except CodeMessageError as e:
                return {'success': False, 'code': e.code, 'message': e.message}
            # this is a workaround for the current protocol. Should be fixed when lbryum support is over and we
            # are able to use the modern get_transaction call, which accepts verbose to show height and other fields
            height = await self.ledger.network.get_transaction_height(txid)
            tx = self.ledger.transaction_class(unhexlify(_raw))
            if tx and height > 0:
                await self.ledger.maybe_verify_transaction(tx, height + 1)  # off by one from server side, yes...
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

    @staticmethod
    def get_utxos(account: BaseAccount):
        return account.get_utxos()

    async def claim_name(self, account, name, amount, claim_dict, certificate=None, claim_address=None):
        claim = ClaimDict.load_dict(claim_dict)
        if not claim_address:
            claim_address = await account.receiving.get_or_create_usable_address()
        if certificate:
            claim = claim.sign(
                certificate.private_key, claim_address, certificate.claim_id, curve=SECP256k1, name=name
            )
        existing_claims = await account.get_claims(
            claim_name_type__any={'is_claim': 1, 'is_update': 1},  # exclude is_supports
            claim_name=name
        )
        if len(existing_claims) == 0:
            tx = await Transaction.claim(
                name, claim, amount, claim_address, [account], account
            )
        elif len(existing_claims) == 1:
            tx = await Transaction.update(
                existing_claims[0], claim, amount, claim_address, [account], account
            )
        else:
            raise NameError(f"More than one other claim exists with the name '{name}'.")
        await account.ledger.broadcast(tx)
        await self.old_db.save_claims([self._old_get_temp_claim_info(
            tx, tx.outputs[0], claim_address, claim_dict, name, dewies_to_lbc(amount)
        )])
        # TODO: release reserved tx outputs in case anything fails by this point
        return tx

    async def support_claim(self, claim_name, claim_id, amount, account):
        holding_address = await account.receiving.get_or_create_usable_address()
        tx = await Transaction.support(claim_name, claim_id, amount, holding_address, [account], account)
        await account.ledger.broadcast(tx)
        await self.old_db.save_supports(claim_id, [{
                'txid': tx.id,
                'nout': tx.position,
                'address': holding_address,
                'claim_id': claim_id,
                'amount': dewies_to_lbc(amount)
        }])
        return tx

    async def tip_claim(self, amount, claim_id, account):
        claim_to_tip = await self.get_claim_by_claim_id(claim_id)
        tx = await Transaction.support(
            claim_to_tip['name'], claim_id, amount, claim_to_tip['address'], [account], account
        )
        await account.ledger.broadcast(tx)
        await self.old_db.save_supports(claim_id, [{
                'txid': tx.id,
                'nout': tx.position,
                'address': claim_to_tip['address'],
                'claim_id': claim_id,
                'amount': dewies_to_lbc(amount)
        }])
        return tx

    async def abandon_claim(self, claim_id, txid, nout, account):
        claim = await account.get_claim(claim_id=claim_id, txid=txid, nout=nout)
        if not claim:
            raise Exception('No claim found for the specified claim_id or txid:nout')

        tx = await Transaction.abandon(claim, [account], account)
        await account.ledger.broadcast(tx)
        # TODO: release reserved tx outputs in case anything fails by this point
        return tx

    async def claim_new_channel(self, channel_name, amount, account):
        address = await account.receiving.get_or_create_usable_address()
        cert, key = generate_certificate()
        tx = await Transaction.claim(channel_name, cert, amount, address, [account], account)
        await account.ledger.broadcast(tx)
        account.add_certificate_private_key(tx.outputs[0].ref, key.decode())
        # TODO: release reserved tx outputs in case anything fails by this point

        await self.old_db.save_claims([self._old_get_temp_claim_info(
            tx, tx.outputs[0], address, cert, channel_name, dewies_to_lbc(amount)
        )])
        return tx

    def _old_get_temp_claim_info(self, tx, txo, address, claim_dict, name, bid):
        return {
            "claim_id": txo.claim_id,
            "name": name,
            "amount": bid,
            "address": address,
            "txid": tx.id,
            "nout": txo.position,
            "value": claim_dict,
            "height": -1,
            "claim_sequence": -1,
        }

    def get_certificates(self, private_key_accounts, exclude_without_key=True, **constraints):
        return self.db.get_certificates(
            private_key_accounts=private_key_accounts,
            exclude_without_key=exclude_without_key,
            **constraints
        )

    def update_peer_address(self, peer, address):
        pass  # TODO: Data payments is disabled

    def get_unused_address_for_peer(self, peer):
        # TODO: Data payments is disabled
        return self.get_unused_address()

    def add_expected_payment(self, peer, amount):
        pass  # TODO: Data payments is disabled

    def send_points(self, reserved_points, amount):
        defer.succeed(True)  # TODO: Data payments is disabled

    def cancel_point_reservation(self, reserved_points):
        pass # fixme: disabled for now.

    def save(self):
        for wallet in self.wallets:
            wallet.save()

    def get_block(self, block_hash=None, height=None):
        if height is None:
            height = self.ledger.headers.height
        if block_hash is None:
            block_hash = self.ledger.headers.hash(height).decode()
        return self.ledger.network.get_block(block_hash)

    def get_claim_by_claim_id(self, claim_id):
        return self.ledger.get_claim_by_claim_id(claim_id)

    def get_claim_by_outpoint(self, txid, nout):
        return self.ledger.get_claim_by_outpoint(txid, nout)


class ClientRequest:
    def __init__(self, request_dict, response_identifier=None):
        self.request_dict = request_dict
        self.response_identifier = response_identifier


class LBRYcrdAddressRequester:

    def __init__(self, wallet):
        self.wallet = wallet
        self._protocols = []

    def send_next_request(self, peer, protocol):
        if not protocol in self._protocols:
            r = ClientRequest({'lbrycrd_address': True}, 'lbrycrd_address')
            d = protocol.add_request(r)
            d.addCallback(self._handle_address_response, peer, r, protocol)
            d.addErrback(self._request_failed, peer)
            self._protocols.append(protocol)
            return defer.succeed(True)
        else:
            return defer.succeed(False)

    def _handle_address_response(self, response_dict, peer, request, protocol):
        if request.response_identifier not in response_dict:
            raise ValueError(
                f"Expected {request.response_identifier} in response but did not get it")
        assert protocol in self._protocols, "Responding protocol is not in our list of protocols"
        address = response_dict[request.response_identifier]
        self.wallet.update_peer_address(peer, address)

    def _request_failed(self, error, peer):
        raise Exception(
            "A peer failed to send a valid public key response. Error: {}, peer: {}".format(
                error.getErrorMessage(), str(peer)
            )
        )


class LBRYcrdAddressQueryHandlerFactory:

    def __init__(self, wallet):
        self.wallet = wallet

    def build_query_handler(self):
        q_h = LBRYcrdAddressQueryHandler(self.wallet)
        return q_h

    def get_primary_query_identifier(self):
        return 'lbrycrd_address'

    def get_description(self):
        return "LBRYcrd Address - an address for receiving payments via LBRYcrd"


class LBRYcrdAddressQueryHandler:

    def __init__(self, wallet):
        self.wallet = wallet
        self.query_identifiers = ['lbrycrd_address']
        self.address = None
        self.peer = None

    def register_with_request_handler(self, request_handler, peer):
        self.peer = peer
        request_handler.register_query_handler(self, self.query_identifiers)

    @defer.inlineCallbacks
    def handle_queries(self, queries):
        if self.query_identifiers[0] in queries:
            address = yield f2d(self.wallet.get_unused_address_for_peer(self.peer))
            self.address = address
            fields = {'lbrycrd_address': address}
            return fields
        if self.address is None:
            raise Exception("Expected a request for an address, but did not receive one")
        else:
            return {}
