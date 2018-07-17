import os
import six
import json
from binascii import hexlify
from twisted.internet import defer

from torba.manager import WalletManager as BaseWalletManager

from lbryschema.uri import parse_lbry_uri
from lbryschema.error import URIParseError
from lbryschema.claim import ClaimDict

from .ledger import MainNetLedger  # pylint: disable=unused-import
from .account import generate_certificate
from .transaction import Transaction
from .database import WalletDatabase  # pylint: disable=unused-import


if six.PY3:
    buffer = memoryview


class BackwardsCompatibleNetwork(object):
    def __init__(self, manager):
        self.manager = manager

    def get_local_height(self):
        return len(self.manager.ledgers.values()[0].headers)

    def get_server_height(self):
        return self.get_local_height()


class LbryWalletManager(BaseWalletManager):

    @property
    def ledger(self):  # type: () -> MainNetLedger
        return self.default_account.ledger

    @property
    def db(self):  # type: () -> WalletDatabase
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

    def check_locked(self):
        return defer.succeed(False)

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

        wallet_file_path = os.path.join(settings['lbryum_wallet_dir'], 'default_wallet')
        if os.path.exists(wallet_file_path):
            with open(wallet_file_path, 'r') as f:
                json_data = f.read()
                json_dict = json.loads(json_data)
            # TODO: After several public releases of new torba based wallet, we can delete
            #       this lbryum->torba conversion code and require that users who still
            #       have old structured wallets install one of the earlier releases that
            #       still has the below conversion code.
            if 'master_public_keys' in json_dict:
                json_data = json.dumps({
                    'version': 1,
                    'name': 'My Wallet',
                    'accounts': [{
                        'version': 1,
                        'name': 'Main Account',
                        'ledger': 'lbc_mainnet',
                        'encrypted': json_dict['use_encryption'],
                        'seed': json_dict['seed'],
                        'seed_version': json_dict['seed_version'],
                        'private_key': json_dict['master_private_keys']['x/'],
                        'public_key': json_dict['master_public_keys']['x/'],
                        'certificates': json_dict.get('claim_certificates', []),
                        'receiving_gap': 20,
                        'change_gap': 6,
                        'receiving_maximum_uses_per_address': 2,
                        'change_maximum_uses_per_address': 2,
                        'is_hd': True
                    }]
                }, indent=4, sort_keys=True)
                with open(wallet_file_path, 'w') as f:
                    f.write(json_data)

        return cls.from_config({
            'ledgers': {ledger_id: ledger_config},
            'wallets': [wallet_file_path]
        })

    def get_best_blockhash(self):
        return defer.succeed('')

    def get_unused_address(self):
        return self.default_account.receiving.get_or_create_usable_address()

    def get_new_address(self):
        return self.get_unused_address()

    def reserve_points(self, address, amount):
        # TODO: check if we have enough to cover amount
        return ReservedPoints(address, amount)

    def send_points_to_address(self, reserved, amount):
        destination_address = reserved.identifier.encode('latin1')
        return self.send_amount_to_address(amount, destination_address)

    def get_wallet_info_query_handler_factory(self):
        return LBRYcrdAddressQueryHandlerFactory(self)

    def get_info_exchanger(self):
        return LBRYcrdAddressRequester(self)

    def resolve(self, *uris, **kwargs):
        page = kwargs.get('page', 0)
        page_size = kwargs.get('page_size', 10)
        ledger = self.default_account.ledger  # type: MainNetLedger
        return ledger.resolve(page, page_size, *uris)

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
        tx = yield Transaction.claim(name.encode(), claim, amount, claim_address, [account], account)
        yield account.ledger.broadcast(tx)
        yield self.old_db.save_claims([self._old_get_temp_claim_info(
            tx, tx.outputs[0], claim_address, claim_dict, name, amount
        )])
        # TODO: release reserved tx outputs in case anything fails by this point
        defer.returnValue(tx)

    def _old_get_temp_claim_info(self, tx, txo, address, claim_dict, name, bid):
        if isinstance(address, buffer):
            address = str(address)
        return {
            "claim_id": hexlify(tx.get_claim_id(txo.position)).decode(),
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
    def claim_new_channel(self, channel_name, amount):
        try:
            parsed = parse_lbry_uri(channel_name)
            if not parsed.is_channel:
                raise Exception("Cannot make a new channel for a non channel name")
            if parsed.path:
                raise Exception("Invalid channel uri")
        except (TypeError, URIParseError):
            raise Exception("Invalid channel name")
        if amount <= 0:
            raise Exception("Invalid amount")
        account = self.default_account
        address = yield account.receiving.get_or_create_usable_address()
        cert, key = generate_certificate()
        tx = yield Transaction.claim(channel_name.encode(), cert, amount, address, [account], account)
        yield account.ledger.broadcast(tx)
        account.add_certificate_private_key(tx, 0, key.decode())
        # TODO: release reserved tx outputs in case anything fails by this point
        defer.returnValue(tx)

    def get_certificates(self, name):
        return self.db.get_certificates(name, [self.default_account], exclude_without_key=True)

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


class ReservedPoints(object):
    def __init__(self, identifier, amount):
        self.identifier = identifier
        self.amount = amount


class ClientRequest(object):
    def __init__(self, request_dict, response_identifier=None):
        self.request_dict = request_dict
        self.response_identifier = response_identifier


class LBRYcrdAddressRequester(object):

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


class LBRYcrdAddressQueryHandlerFactory(object):

    def __init__(self, wallet):
        self.wallet = wallet

    def build_query_handler(self):
        q_h = LBRYcrdAddressQueryHandler(self.wallet)
        return q_h

    def get_primary_query_identifier(self):
        return 'lbrycrd_address'

    def get_description(self):
        return "LBRYcrd Address - an address for receiving payments via LBRYcrd"


class LBRYcrdAddressQueryHandler(object):

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
