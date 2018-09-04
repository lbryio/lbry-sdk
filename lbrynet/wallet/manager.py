import os
import json
import logging
from twisted.internet import defer

from torba.basemanager import BaseWalletManager

from lbryschema.claim import ClaimDict

from .ledger import MainNetLedger
from .account import generate_certificate
from .transaction import Transaction
from .database import WalletDatabase

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
        # TODO: implement this
        return False

    @property
    def is_first_run(self):
        return True

    @property
    def is_wallet_unlocked(self):
        return True

    def check_locked(self):
        return defer.succeed(False)

    @staticmethod
    def migrate_lbryum_to_torba(path):
        if not os.path.exists(path):
            return
        with open(path, 'r') as f:
            unmigrated_json = f.read()
            unmigrated = json.loads(unmigrated_json)
        # TODO: After several public releases of new torba based wallet, we can delete
        #       this lbryum->torba conversion code and require that users who still
        #       have old structured wallets install one of the earlier releases that
        #       still has the below conversion code.
        if 'master_public_keys' not in unmigrated:
            return
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
                    'receiving': {'gap': 20, 'maximum_uses_per_address': 2},
                    'change': {'gap': 6, 'maximum_uses_per_address': 2}
                }
            }]
        }, indent=4, sort_keys=True)
        mode = os.stat(path).st_mode
        i = 1
        backup_path_template = os.path.join(os.path.dirname(path), "old_lbryum_wallet") + "_%i"
        while os.path.isfile(backup_path_template % i):
            i += 1
        os.rename(path, backup_path_template % i)
        temp_path = "%s.tmp.%s" % (path, os.getpid())
        with open(temp_path, "w") as f:
            f.write(migrated_json)
            f.flush()
            os.fsync(f.fileno())
        os.rename(temp_path, path)
        os.chmod(path, mode)

    @classmethod
    def from_lbrynet_config(cls, settings, db):

        ledger_id = {
            'lbrycrd_main':    'lbc_mainnet',
            'lbrycrd_testnet': 'lbc_testnet',
            'lbrycrd_regtest': 'lbc_regtest'
        }[settings['blockchain_name']]

        ledger_config = {
            'auto_connect': True,
            'default_servers': settings['lbryum_servers'],
            'data_path': settings['lbryum_wallet_dir'],
            'use_keyring': settings['use_keyring'],
            #'db': db
        }

        wallets_directory = os.path.join(settings['lbryum_wallet_dir'], 'wallets')
        if not os.path.exists(wallets_directory):
            os.mkdir(wallets_directory)

        wallet_file_path = os.path.join(wallets_directory, 'default_wallet')

        cls.migrate_lbryum_to_torba(wallet_file_path)

        manager = cls.from_config({
            'ledgers': {ledger_id: ledger_config},
            'wallets': [wallet_file_path]
        })
        if manager.default_account is None:
            ledger = manager.get_or_create_ledger('lbc_mainnet')
            log.info('Wallet at %s is empty, generating a default account.', wallet_file_path)
            manager.default_wallet.generate_account(ledger)
            manager.default_wallet.save()
        return manager

    def get_best_blockhash(self):
        return defer.succeed('')

    def get_unused_address(self):
        return self.default_account.receiving.get_or_create_usable_address()

    def get_new_address(self):
        return self.get_unused_address()

    def list_addresses(self):
        return self.default_account.get_addresses()

    def reserve_points(self, address, amount):
        # TODO: check if we have enough to cover amount
        return ReservedPoints(address, amount)

    @defer.inlineCallbacks
    def send_amount_to_address(self, amount: int, destination_address: bytes):
        account = self.default_account
        tx = yield Transaction.pay(amount, destination_address, [account], account)
        yield account.ledger.broadcast(tx)
        return tx

    def send_points_to_address(self, reserved: ReservedPoints, amount: int):
        destination_address: bytes = reserved.identifier.encode('latin1')
        return self.send_amount_to_address(amount, destination_address)

    def get_wallet_info_query_handler_factory(self):
        return LBRYcrdAddressQueryHandlerFactory(self)

    def get_info_exchanger(self):
        return LBRYcrdAddressRequester(self)

    @defer.inlineCallbacks
    def resolve(self, *uris, **kwargs):
        page = kwargs.get('page', 0)
        page_size = kwargs.get('page_size', 10)
        check_cache = kwargs.get('check_cache', False)  # TODO: put caching back (was force_refresh parameter)
        ledger = self.default_account.ledger  # type: MainNetLedger
        results = yield ledger.resolve(page, page_size, *uris)
        yield self.old_db.save_claims_for_resolve(
            (value for value in results.values() if 'error' not in value))
        defer.returnValue(results)

    def get_name_claims(self):
        return defer.succeed([])

    def address_is_mine(self, address):
        return defer.succeed(True)

    def get_history(self):
        return defer.succeed([])

    @defer.inlineCallbacks
    def claim_name(self, name, amount, claim_dict, certificate=None, claim_address=None):
        account = self.default_account
        claim = ClaimDict.load_dict(claim_dict)
        if not claim_address:
            claim_address = yield account.receiving.get_or_create_usable_address()
        if certificate:
            claim = claim.sign(
                certificate.private_key, claim_address, certificate.claim_id
            )
        existing_claims = yield account.get_unspent_outputs(include_claims=True, claim_name=name)
        if len(existing_claims) == 0:
            tx = yield Transaction.claim(
                name, claim, amount, claim_address, [account], account
            )
        elif len(existing_claims) == 1:
            tx = yield Transaction.update(
                existing_claims[0], claim, amount, claim_address, [account], account
            )
        else:
            raise NameError("More than one other claim exists with the name '{}'.".format(name))
        yield account.ledger.broadcast(tx)
        yield self.old_db.save_claims([self._old_get_temp_claim_info(
            tx, tx.outputs[0], claim_address, claim_dict, name, amount
        )])
        # TODO: release reserved tx outputs in case anything fails by this point
        defer.returnValue(tx)

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

    @defer.inlineCallbacks
    def support_claim(self, claim_name, claim_id, amount, account):
        holding_address = yield account.receiving.get_or_create_usable_address()
        tx = yield Transaction.support(claim_name, claim_id, amount, holding_address, [account], account)
        yield account.ledger.broadcast(tx)
        return tx

    @defer.inlineCallbacks
    def tip_claim(self, amount, claim_id, account):
        claim_to_tip = yield self.get_claim_by_claim_id(claim_id)
        tx = yield Transaction.support(
            claim_to_tip['name'], claim_id, amount, claim_to_tip['address'], [account], account
        )
        yield account.ledger.broadcast(tx)
        return tx

    @defer.inlineCallbacks
    def abandon_claim(self, claim_id, txid, nout):
        account = self.default_account
        claim = yield account.get_claim(claim_id)
        tx = yield Transaction.abandon(claim, [account], account)
        yield account.ledger.broadcast(tx)
        # TODO: release reserved tx outputs in case anything fails by this point
        defer.returnValue(tx)

    @defer.inlineCallbacks
    def claim_new_channel(self, channel_name, amount):
        account = self.default_account
        address = yield account.receiving.get_or_create_usable_address()
        cert, key = generate_certificate()
        tx = yield Transaction.claim(channel_name, cert, amount, address, [account], account)
        yield account.ledger.broadcast(tx)
        account.add_certificate_private_key(tx.outputs[0].ref, key.decode())
        # TODO: release reserved tx outputs in case anything fails by this point
        defer.returnValue(tx)

    def channel_list(self):
        return self.default_account.get_channels()

    def get_certificates(self, name):
        return self.db.get_certificates(name, self.accounts, exclude_without_key=True)

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
                "Expected {} in response but did not get it".format(request.response_identifier))
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

    def handle_queries(self, queries):

        def create_response(address):
            self.address = address
            fields = {'lbrycrd_address': address}
            return fields

        if self.query_identifiers[0] in queries:
            d = self.wallet.get_unused_address_for_peer(self.peer)
            d.addCallback(create_response)
            return d
        if self.address is None:
            raise Exception("Expected a request for an address, but did not receive one")
        else:
            return defer.succeed({})
