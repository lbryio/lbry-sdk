import os
from twisted.internet import defer

from .constants import COIN
from .manager import WalletManager


class BackwardsCompatibleNetwork:
    def __init__(self, manager):
        self.manager = manager

    def get_local_height(self):
        return len(self.manager.ledgers.values()[0].headers)

    def get_server_height(self):
        return self.get_local_height()


class BackwardsCompatibleWalletManager(WalletManager):

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
        coin_id = 'lbc_{}'.format(settings['blockchain_name'][-7:])
        wallet_manager = cls.from_config({
            'ledgers': {coin_id: {'default_servers': settings['lbryum_servers']}}
        })
        ledger = wallet_manager.ledgers.values()[0]
        wallet_manager.create_wallet(
            os.path.join(settings['lbryum_wallet_dir'], 'default_torba_wallet'),
            ledger.coin_class
        )
        return wallet_manager

    def start(self):
        return self.start_ledgers()

    def stop(self):
        return self.stop_ledgers()

    def get_balance(self):
        return self.default_account.get_balance()

    def get_best_blockhash(self):
        return defer.succeed('')

    def get_unused_address(self):
        return defer.succeed(self.default_account.get_least_used_receiving_address())

    def reserve_points(self, address, amount):
        # TODO: check if we have enough to cover amount
        return ReservedPoints(address, amount)

    def send_points_to_address(self, reserved, amount):
        account = self.default_account
        coin = account.coin
        ledger = coin.ledger
        tx_class = ledger.transaction_class
        in_class, out_class = tx_class.input_class, tx_class.output_class

        destination_address = reserved.identifier.encode('latin1')

        outputs = [
            out_class.pay_pubkey_hash(amount*COIN, coin.address_to_hash160(destination_address))
        ]

        amount += 0.001

        amount = amount*COIN

        # TODO: use CoinSelector
        utxos = account.get_unspent_utxos()
        total = account.get_balance()
        if amount < total and total-amount > 0.00001*COIN:
            change_destination = account.get_least_used_change_address()
            outputs.append(
                out_class.pay_pubkey_hash(total-amount, coin.address_to_hash160(change_destination))
            )

        tx = tx_class() \
            .add_inputs([in_class.spend(utxo) for utxo in utxos]) \
            .add_outputs(outputs)\
            .sign(account)

        return ledger.broadcast(tx)

    def get_wallet_info_query_handler_factory(self):
        return LBRYcrdAddressQueryHandlerFactory(self)

    def get_info_exchanger(self):
        return LBRYcrdAddressRequester(self)


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
