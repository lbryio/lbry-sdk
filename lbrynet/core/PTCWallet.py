from collections import defaultdict
import logging
import os
import unqlite
import time
from Crypto.Hash import SHA512
from Crypto.PublicKey import RSA
from lbrynet.core.client.ClientRequest import ClientRequest
from lbrynet.core.Error import RequestCanceledError
from lbrynet.interfaces import IRequestCreator, IQueryHandlerFactory, IQueryHandler, IWallet
from lbrynet.pointtraderclient import pointtraderclient
from twisted.internet import defer, threads
from zope.interface import implements
from twisted.python.failure import Failure
from lbrynet.core.Wallet import ReservedPoints


log = logging.getLogger(__name__)


class PTCWallet(object):
    """This class sends payments to peers and also ensures that expected payments are received.
       This class is only intended to be used for testing."""
    implements(IWallet)

    def __init__(self, db_dir):
        self.db_dir = db_dir
        self.db = None
        self.private_key = None
        self.encoded_public_key = None
        self.peer_pub_keys = {}
        self.queued_payments = defaultdict(int)
        self.expected_payments = defaultdict(list)
        self.received_payments = defaultdict(list)
        self.next_manage_call = None
        self.payment_check_window = 3 * 60  # 3 minutes
        self.new_payments_expected_time = time.time() - self.payment_check_window
        self.known_transactions = []
        self.total_reserved_points = 0.0
        self.wallet_balance = 0.0

    def manage(self):
        """Send payments, ensure expected payments are received"""

        from twisted.internet import reactor

        if time.time() < self.new_payments_expected_time + self.payment_check_window:
            d1 = self._get_new_payments()
        else:
            d1 = defer.succeed(None)
        d1.addCallback(lambda _: self._check_good_standing())
        d2 = self._send_queued_points()
        self.next_manage_call = reactor.callLater(60, self.manage)
        dl = defer.DeferredList([d1, d2])
        dl.addCallback(lambda _: self.get_balance())

        def set_balance(balance):
            self.wallet_balance = balance

        dl.addCallback(set_balance)
        return dl

    def stop(self):
        if self.next_manage_call is not None:
            self.next_manage_call.cancel()
            self.next_manage_call = None
        d = self.manage()
        self.next_manage_call.cancel()
        self.next_manage_call = None
        self.db = None
        return d

    def start(self):

        def save_key(success, private_key):
            if success is True:
                self._save_private_key(private_key.exportKey())
                return True
            return False

        def register_private_key(private_key):
            self.private_key = private_key
            self.encoded_public_key = self.private_key.publickey().exportKey()
            d_r = pointtraderclient.register_new_account(private_key)
            d_r.addCallback(save_key, private_key)
            return d_r

        def ensure_private_key_exists(encoded_private_key):
            if encoded_private_key is not None:
                self.private_key = RSA.importKey(encoded_private_key)
                self.encoded_public_key = self.private_key.publickey().exportKey()
                return True
            else:
                create_d = threads.deferToThread(RSA.generate, 4096)
                create_d.addCallback(register_private_key)
                return create_d

        def start_manage():
            self.manage()
            return True
        d = self._open_db()
        d.addCallback(lambda _: self._get_wallet_private_key())
        d.addCallback(ensure_private_key_exists)
        d.addCallback(lambda _: start_manage())
        return d

    def get_info_exchanger(self):
        return PointTraderKeyExchanger(self)

    def get_wallet_info_query_handler_factory(self):
        return PointTraderKeyQueryHandlerFactory(self)

    def reserve_points(self, peer, amount):
        """
        Ensure a certain amount of points are available to be sent as payment, before the service is rendered

        @param peer: The peer to which the payment will ultimately be sent

        @param amount: The amount of points to reserve

        @return: A ReservedPoints object which is given to send_points once the service has been rendered
        """
        if self.wallet_balance >= self.total_reserved_points + amount:
            self.total_reserved_points += amount
            return ReservedPoints(peer, amount)
        return None

    def cancel_point_reservation(self, reserved_points):
        """
        Return all of the points that were reserved previously for some ReservedPoints object

        @param reserved_points: ReservedPoints previously returned by reserve_points

        @return: None
        """
        self.total_reserved_points -= reserved_points.amount

    def send_points(self, reserved_points, amount):
        """
        Schedule a payment to be sent to a peer

        @param reserved_points: ReservedPoints object previously returned by reserve_points

        @param amount: amount of points to actually send, must be less than or equal to the
            amount reserved in reserved_points

        @return: Deferred which fires when the payment has been scheduled
        """
        self.queued_payments[reserved_points.identifier] += amount
        # make any unused points available
        self.total_reserved_points -= reserved_points.amount - amount
        reserved_points.identifier.update_stats('points_sent', amount)
        d = defer.succeed(True)
        return d

    def _send_queued_points(self):
        ds = []
        for peer, points in self.queued_payments.items():
            if peer in self.peer_pub_keys:
                d = pointtraderclient.send_points(self.private_key, self.peer_pub_keys[peer], points)
                self.wallet_balance -= points
                self.total_reserved_points -= points
                ds.append(d)
                del self.queued_payments[peer]
            else:
                log.warning("Don't have a payment address for peer %s. Can't send %s points.",
                            str(peer), str(points))
        return defer.DeferredList(ds)

    def get_balance(self):
        """Return the balance of this wallet"""
        d = pointtraderclient.get_balance(self.private_key)
        return d

    def add_expected_payment(self, peer, amount):
        """Increase the number of points expected to be paid by a peer"""
        self.expected_payments[peer].append((amount, time.time()))
        self.new_payments_expected_time = time.time()
        peer.update_stats('expected_points', amount)

    def set_public_key_for_peer(self, peer, pub_key):
        self.peer_pub_keys[peer] = pub_key

    def _get_new_payments(self):

        def add_new_transactions(transactions):
            for transaction in transactions:
                if transaction[1] == self.encoded_public_key:
                    t_hash = SHA512.new()
                    t_hash.update(transaction[0])
                    t_hash.update(transaction[1])
                    t_hash.update(str(transaction[2]))
                    t_hash.update(transaction[3])
                    if t_hash.hexdigest() not in self.known_transactions:
                        self.known_transactions.append(t_hash.hexdigest())
                        self._add_received_payment(transaction[0], transaction[2])

        d = pointtraderclient.get_recent_transactions(self.private_key)
        d.addCallback(add_new_transactions)
        return d

    def _add_received_payment(self, encoded_other_public_key, amount):
        self.received_payments[encoded_other_public_key].append((amount, time.time()))

    def _check_good_standing(self):
        for peer, expected_payments in self.expected_payments.iteritems():
            expected_cutoff = time.time() - 90
            min_expected_balance = sum([a[0] for a in expected_payments if a[1] < expected_cutoff])
            received_balance = 0
            if self.peer_pub_keys[peer] in self.received_payments:
                received_balance = sum([a[0] for a in self.received_payments[self.peer_pub_keys[peer]]])
            if min_expected_balance > received_balance:
                log.warning("Account in bad standing: %s (pub_key: %s), expected amount = %s, received_amount = %s",
                            str(peer), self.peer_pub_keys[peer], str(min_expected_balance), str(received_balance))

    def _open_db(self):
        def open_db():
            self.db = unqlite.UnQLite(os.path.join(self.db_dir, "ptcwallet.db"))
        return threads.deferToThread(open_db)

    def _save_private_key(self, private_key):
        def save_key():
            self.db['private_key'] = private_key
        return threads.deferToThread(save_key)

    def _get_wallet_private_key(self):
        def get_key():
            if 'private_key' in self.db:
                return self.db['private_key']
            return None
        return threads.deferToThread(get_key)


class PointTraderKeyExchanger(object):
    implements([IRequestCreator])

    def __init__(self, wallet):
        self.wallet = wallet
        self._protocols = []

    ######### IRequestCreator #########

    def send_next_request(self, peer, protocol):
        if not protocol in self._protocols:
            r = ClientRequest({'public_key': self.wallet.encoded_public_key},
                              'public_key')
            d = protocol.add_request(r)
            d.addCallback(self._handle_exchange_response, peer, r, protocol)
            d.addErrback(self._request_failed, peer)
            self._protocols.append(protocol)
            return defer.succeed(True)
        else:
            return defer.succeed(False)

    ######### internal calls #########

    def _handle_exchange_response(self, response_dict, peer, request, protocol):
        assert request.response_identifier in response_dict, \
            "Expected %s in dict but did not get it" % request.response_identifier
        assert protocol in self._protocols, "Responding protocol is not in our list of protocols"
        peer_pub_key = response_dict[request.response_identifier]
        self.wallet.set_public_key_for_peer(peer, peer_pub_key)
        return True

    def _request_failed(self, err, peer):
        if not err.check(RequestCanceledError):
            log.warning("A peer failed to send a valid public key response. Error: %s, peer: %s",
                        err.getErrorMessage(), str(peer))
            return err


class PointTraderKeyQueryHandlerFactory(object):
    implements(IQueryHandlerFactory)

    def __init__(self, wallet):
        self.wallet = wallet

    ######### IQueryHandlerFactory #########

    def build_query_handler(self):
        q_h = PointTraderKeyQueryHandler(self.wallet)
        return q_h

    def get_primary_query_identifier(self):
        return 'public_key'

    def get_description(self):
        return "Point Trader Address - an address for receiving payments on the point trader testing network"


class PointTraderKeyQueryHandler(object):
    implements(IQueryHandler)

    def __init__(self, wallet):
        self.wallet = wallet
        self.query_identifiers = ['public_key']
        self.public_key = None
        self.peer = None

    ######### IQueryHandler #########

    def register_with_request_handler(self, request_handler, peer):
        self.peer = peer
        request_handler.register_query_handler(self, self.query_identifiers)

    def handle_queries(self, queries):
        if self.query_identifiers[0] in queries:
            new_encoded_pub_key = queries[self.query_identifiers[0]]
            try:
                RSA.importKey(new_encoded_pub_key)
            except (ValueError, TypeError, IndexError):
                log.warning("Client sent an invalid public key.")
                return defer.fail(Failure(ValueError("Client sent an invalid public key")))
            self.public_key = new_encoded_pub_key
            self.wallet.set_public_key_for_peer(self.peer, self.public_key)
            log.debug("Received the client's public key: %s", str(self.public_key))
            fields = {'public_key': self.wallet.encoded_public_key}
            return defer.succeed(fields)
        if self.public_key is None:
            log.warning("Expected a public key, but did not receive one")
            return defer.fail(Failure(ValueError("Expected but did not receive a public key")))
        else:
            return defer.succeed({})