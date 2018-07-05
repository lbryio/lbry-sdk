import os
from twisted.internet import defer

from torba.basetransaction import NULL_HASH
from torba.constants import COIN
from torba.coinselection import CoinSelector
from torba.manager import WalletManager as BaseWalletManager

from lbryschema.uri import parse_lbry_uri
from lbryschema.error import URIParseError

from .ledger import MainNetLedger
from .account import generate_certificate
from .transaction import Transaction


class BackwardsCompatibleNetwork:
    def __init__(self, manager):
        self.manager = manager

    def get_local_height(self):
        return len(self.manager.ledgers.values()[0].headers)

    def get_server_height(self):
        return self.get_local_height()


class LbryWalletManager(BaseWalletManager):

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
    def from_old_config(cls, settings):

        ledger_id = {
            'lbrycrd_main':    'lbc_mainnet',
            'lbrycrd_testnet': 'lbc_testnet',
            'lbrycrd_regtest': 'lbc_regtest'
        }[settings['blockchain_name']]

        ledger_config = {
            'auto_connect': True,
            'default_servers': settings['lbryum_servers'],
            'wallet_path': settings['lbryum_wallet_dir'],
            'use_keyring': settings['use_keyring']
        }

        return cls.from_config({
            'ledgers': {ledger_id: ledger_config},
            'wallets': [os.path.join(settings['lbryum_wallet_dir'], 'default_wallet')]
        })

    def get_best_blockhash(self):
        return defer.succeed('')

    def get_unused_address(self):
        return defer.succeed(self.default_account.get_least_used_receiving_address())

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
        ledger = self.default_account.ledger  # type: MainNetLedger
        return ledger.resolve(*uris)

    def get_name_claims(self):
        return defer.succeed([])

    def address_is_mine(self, address):
        return defer.succeed(True)

    def get_history(self):
        return defer.succeed([])

    def claim_name(self, name, amount, claim):
        pass

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
        account.add_certificate(tx.get_claim_id(0), key)
        # TODO: release reserved tx outputs in case anything fails by this point
        defer.returnValue(tx)


class ReservedPoints:
    def __init__(self, identifier, amount):
        self.identifier = identifier
        self.amount = amount


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
        raise Exception("A peer failed to send a valid public key response. Error: %s, peer: %s",
                        error.getErrorMessage(), str(peer))


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
