import datetime
import logging
import os
import json
import time

from twisted.internet import threads, reactor, defer, task
from twisted.python.failure import Failure
from twisted.enterprise import adbapi

from collections import defaultdict, deque
from zope.interface import implements
from decimal import Decimal

import lbryum.wallet
from lbryum.network import Network
from lbryum.simple_config import SimpleConfig
from lbryum.constants import COIN
from lbryum.commands import known_commands, Commands

from lbryschema.uri import parse_lbry_uri
from lbryschema.claim import ClaimDict
from lbryschema.error import DecodeError
from lbryschema.decode import smart_decode

from lbrynet import conf
from lbrynet.core.sqlite_helpers import rerun_if_locked
from lbrynet.interfaces import IRequestCreator, IQueryHandlerFactory, IQueryHandler, IWallet
from lbrynet.core.client.ClientRequest import ClientRequest
from lbrynet.core.Error import RequestCanceledError, InsufficientFundsError, UnknownNameError
from lbrynet.core.Error import UnknownClaimID, UnknownURI, NegativeFundsError, UnknownOutpoint

log = logging.getLogger(__name__)


class ReservedPoints(object):
    def __init__(self, identifier, amount):
        self.identifier = identifier
        self.amount = amount


class ClaimOutpoint(dict):
    def __init__(self, txid, nout):
        if len(txid) != 64:
            raise TypeError('{} is not a txid'.format(txid))
        self['txid'] = txid
        self['nout'] = nout

    def __repr__(self):
        return "{}:{}".format(self['txid'], self['nout'])

    def __eq__(self, compare):
        if isinstance(compare, dict):
            # TODO: lbryum returns nout's in dicts as "nOut" , need to fix this
            if 'nOut' in compare:
                return (self['txid'], self['nout']) == (compare['txid'], compare['nOut'])
            elif 'nout' in compare:
                return (self['txid'], self['nout']) == (compare['txid'], compare['nout'])
        elif isinstance(compare, (str, unicode)):
            return compare == self.__repr__()
        else:
            raise TypeError('cannot compare {}'.format(type(compare)))

    def __ne__(self, compare):
        return not self.__eq__(compare)


class CachedClaim(object):
    def __init__(self, claim_id, claim, claim_sequence, address, height, amount, supports,
                 channal_name, signature_is_valid, cache_timestamp, name, txid, nout):
        self.claim_id = claim_id
        self.claim = claim
        self.claim_sequence = claim_sequence
        self.address = address
        self.height = height
        self.amount = amount
        self.supports = [] if not supports else json.loads(supports)
        self.effective_amount = self.amount + sum([x['amount'] for x in self.supports])
        self.channel_name = channal_name
        self.signature_is_valid = signature_is_valid
        self.cache_timestamp = cache_timestamp
        self.name = name
        self.txid = txid
        self.nout = nout

    def response_dict(self, check_expires=True):
        if check_expires:
            if (time.time() - int(self.cache_timestamp)) > conf.settings['cache_time']:
                return
        claim = {
            "height": self.height,
            "address": self.address,
            "claim_id": self.claim_id,
            "claim_sequence": self.claim_sequence,
            "effective_amount": self.effective_amount,
            "has_signature": self.claim.has_signature,
            "name": self.name,
            "hex": self.claim.serialized.encode('hex'),
            "value": self.claim.claim_dict,
            "txid": self.txid,
            "amount": self.amount,
            "decoded_claim": True,
            "supports": self.supports,
            "nout": self.nout
        }
        if self.channel_name is not None:
            claim['channel_name'] = self.channel_name
        if self.signature_is_valid is not None:
            claim['signature_is_valid'] = bool(self.signature_is_valid)
        return claim


class MetaDataStorage(object):
    def load(self):
        return defer.succeed(True)

    def save_name_metadata(self, name, claim_outpoint, sd_hash):
        return defer.succeed(True)

    def get_claim_metadata_for_sd_hash(self, sd_hash):
        return defer.succeed(True)

    def update_claimid(self, claim_id, name, claim_outpoint):
        return defer.succeed(True)

    def get_claimid_for_tx(self, claim_outpoint):
        return defer.succeed(True)

    @defer.inlineCallbacks
    def get_cached_claim(self, claim_id, check_expire=True):
        cache_info = yield self._get_cached_claim(claim_id)
        response = None
        if cache_info:
            cached_claim = CachedClaim(claim_id, *cache_info)
            response = cached_claim.response_dict(check_expires=check_expire)
        defer.returnValue(response)

    def _get_cached_claim(self, claim_id):
        return defer.succeed(None)

    def save_claim_to_cache(self, claim_id, claim_sequence, claim, claim_address, height, amount,
                            supports, channel_name, signature_is_valid):
        return defer.succeed(True)

    def save_claim_to_uri_cache(self, uri, claim_id, certificate_id=None):
        return defer.succeed(None)

    def get_cached_claim_for_uri(self, uri, check_expire=True):
        return defer.succeed(None)


class InMemoryStorage(MetaDataStorage):
    def __init__(self):
        self.metadata = {}
        self.claimids = {}
        self.claim_dicts = {}
        self.uri_cache = {}
        MetaDataStorage.__init__(self)

    def save_name_metadata(self, name, claim_outpoint, sd_hash):
        self.metadata[sd_hash] = (name, claim_outpoint)
        return defer.succeed(True)

    def get_claim_metadata_for_sd_hash(self, sd_hash):
        try:
            name, claim_outpoint = self.metadata[sd_hash]
            return defer.succeed((name, claim_outpoint['txid'], claim_outpoint['nout']))
        except KeyError:
            return defer.succeed(None)

    def update_claimid(self, claim_id, name, claim_outpoint):
        self.claimids[(name, claim_outpoint['txid'], claim_outpoint['nout'])] = claim_id
        return defer.succeed(True)

    def get_claimid_for_tx(self, claim_outpoint):
        result = None
        for k, claim_id in self.claimids.iteritems():
            if k[1] == claim_outpoint['txid'] and k[2] == claim_outpoint['nout']:
                result = claim_id
                break

        return defer.succeed(result)

    def _get_cached_claim(self, claim_id):
        claim_cache = self.claim_dicts.get(claim_id, None)
        claim_tx_cache = None
        for k, v in self.claimids.iteritems():
            if v == claim_id:
                claim_tx_cache = k
                break

        if claim_cache and claim_tx_cache:
            cached_claim_args = tuple(claim_cache) + tuple(claim_tx_cache)
            return defer.succeed(cached_claim_args)
        return defer.succeed(None)

    def save_claim_to_cache(self, claim_id, claim_sequence, claim, claim_address, height, amount,
                            supports, channel_name, signature_is_valid):
        self.claim_dicts[claim_id] = (claim, claim_sequence, claim_address, height, amount,
                                      supports, channel_name, signature_is_valid, int(time.time()))
        return defer.succeed(True)

    def save_claim_to_uri_cache(self, uri, claim_id, certificate_id=None):
        self.uri_cache[uri] = (claim_id, certificate_id)
        return defer.succeed(None)

    @defer.inlineCallbacks
    def get_cached_claim_for_uri(self, uri, check_expire=True):
        result = self.uri_cache.get(uri, None)
        response = None
        if result:
            claim_id, certificate_id = result
            response = yield self.get_cached_claim(claim_id, check_expire)
            if response and certificate_id:
                certificate = yield self.get_cached_claim(certificate_id, check_expire)
                response['certificate'] = certificate['claim']
        defer.returnValue(response)


class SqliteStorage(MetaDataStorage):
    def __init__(self, db_dir):
        self.db_dir = db_dir
        self.db = adbapi.ConnectionPool('sqlite3', os.path.join(self.db_dir, "blockchainname.db"),
                                        check_same_thread=False)
        MetaDataStorage.__init__(self)

    def load(self):
        def create_tables(transaction):
            transaction.execute("CREATE TABLE IF NOT EXISTS name_metadata (" +
                                "    name TEXT UNIQUE NOT NULL, " +
                                "    txid TEXT NOT NULL, " +
                                "    n INTEGER NOT NULL, " +
                                "    sd_hash TEXT NOT NULL)")
            transaction.execute("create table if not exists claim_ids (" +
                                "    claimId text, " +
                                "    name text, " +
                                "    txid text, " +
                                "    n integer)")
            transaction.execute("CREATE TABLE IF NOT EXISTS claim_cache (" +
                                "    row_id INTEGER PRIMARY KEY AUTOINCREMENT, " +
                                "    claim_id TEXT UNIQUE NOT NULL, " +
                                "    claim_sequence INTEGER, " +
                                "    claim_address TEXT NOT NULL, " +
                                "    height INTEGER NOT NULL, " +
                                "    amount INTEGER NOT NULL, " +
                                "    supports TEXT, " +
                                "    claim_pb TEXT, " +
                                "    channel_name TEXT, " +
                                "    signature_is_valid BOOL, " +
                                "    last_modified TEXT)")
            transaction.execute("CREATE TABLE IF NOT EXISTS uri_cache (" +
                                "    row_id INTEGER PRIMARY KEY AUTOINCREMENT, " +
                                "    uri TEXT UNIQUE NOT NULL, " +
                                "    cache_row INTEGER, " +
                                "    certificate_row INTEGER, " +
                                "    last_modified TEXT)")

        return self.db.runInteraction(create_tables)

    @rerun_if_locked
    @defer.inlineCallbacks
    def save_name_metadata(self, name, claim_outpoint, sd_hash):
        # TODO: refactor the 'claim_ids' table to not be terrible
        txid, nout = claim_outpoint['txid'], claim_outpoint['nout']
        yield self.db.runOperation("INSERT OR REPLACE INTO name_metadata VALUES (?, ?, ?, ?)",
                                       (name, txid, nout, sd_hash))
        defer.returnValue(None)

    @rerun_if_locked
    @defer.inlineCallbacks
    def get_claim_metadata_for_sd_hash(self, sd_hash):
        result = yield self.db.runQuery("SELECT name, txid, n FROM name_metadata WHERE sd_hash=?",
                                        (sd_hash, ))
        response = None
        if result:
            response = result[0]
        defer.returnValue(response)

    @rerun_if_locked
    @defer.inlineCallbacks
    def update_claimid(self, claim_id, name, claim_outpoint):
        txid, nout = claim_outpoint['txid'], claim_outpoint['nout']
        yield self.db.runOperation("INSERT OR IGNORE INTO claim_ids VALUES (?, ?, ?, ?)",
                                   (claim_id, name, txid, nout))
        defer.returnValue(claim_id)

    @rerun_if_locked
    @defer.inlineCallbacks
    def get_claimid_for_tx(self, claim_outpoint):
        result = yield self.db.runQuery("SELECT claimId FROM claim_ids "
                                        "WHERE txid=? AND n=?",
                                        (claim_outpoint['txid'], claim_outpoint['nout']))
        response = None
        if result:
            response = result[0][0]
        defer.returnValue(response)


    @rerun_if_locked
    @defer.inlineCallbacks
    def _fix_malformed_supports_amount(self, row_id, supports, amount):
        """
        this fixes malformed supports and amounts that were entering the cache
        support list of [txid, nout, amount in deweys] instead of list of
        {'txid':,'nout':,'amount':}, with amount specified in dewey

        and also supports could be "[]" (brackets enclosed by double quotes)
        This code can eventually be removed, as new versions should not have this problem
        """
        fixed_supports = None
        fixed_amount = None
        supports = [] if not supports else json.loads(supports)
        if isinstance(supports, (str, unicode)) and supports == '[]':
            fixed_supports = []
        elif len(supports) > 0 and not isinstance(supports[0], dict):
            fixed_supports = []
            fixed_amount = amount / 100000000.0
            for support in supports:
                fixed_supports.append(
                    {'txid':support[0], 'nout':support[1], 'amount':support[2]/100000000.0})
        if fixed_supports is not None:
            log.warn("Malformed support found, fixing it")
            r = yield self.db.runOperation('UPDATE claim_cache SET supports=? WHERE row_id=?',
                                        (json.dumps(fixed_supports), row_id))
            supports = fixed_supports
        if fixed_amount is not None:
            log.warn("Malformed amount found, fixing it")
            r = yield self.db.runOperation('UPDATE claim_cache SET amount=? WHERE row_id=?',
                                        (fixed_amount, row_id))
            amount = fixed_amount

        defer.returnValue((json.dumps(supports), amount))

    @rerun_if_locked
    @defer.inlineCallbacks
    def _get_cached_claim(self, claim_id, check_expire=True):
        r = yield self.db.runQuery("SELECT * FROM claim_cache WHERE claim_id=?", (claim_id, ))
        claim_tx_info = yield self.db.runQuery("SELECT name, txid, n FROM claim_ids "
                                               "WHERE claimId=?", (claim_id, ))
        response = None
        if r and claim_tx_info:
            rid, _, seq, claim_address, height, amount, supports, raw, chan_name, valid, ts = r[0]
            supports, amount = yield self._fix_malformed_supports_amount(rid, supports, amount)
            last_modified = int(ts)
            name, txid, nout = claim_tx_info[0]
            claim = ClaimDict.deserialize(raw.decode('hex'))
            response = (claim, seq, claim_address, height, amount, supports,
                        chan_name, valid, last_modified, name, txid, nout)
        defer.returnValue(response)

    @rerun_if_locked
    @defer.inlineCallbacks
    def save_claim_to_cache(self, claim_id, claim_sequence, claim, claim_address, height, amount,
                            supports, channel_name, signature_is_valid):
        serialized = claim.serialized.encode("hex")
        supports = json.dumps([] or supports)
        now = str(int(time.time()))

        yield self.db.runOperation("INSERT OR REPLACE INTO claim_cache(claim_sequence, "
                                   "                        claim_id, claim_address, height, "
                                   "                        amount, supports, claim_pb, "
                                   "                        channel_name, signature_is_valid, "
                                   "                        last_modified)"
                                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   (claim_sequence, claim_id, claim_address, height, amount,
                                    supports, serialized, channel_name, signature_is_valid, now))
        defer.returnValue(None)

    @rerun_if_locked
    @defer.inlineCallbacks
    def save_claim_to_uri_cache(self, uri, claim_id, certificate_id=None):
        result = yield self.db.runQuery("SELECT row_id, last_modified FROM claim_cache "
                                        "WHERE claim_id=?", (claim_id, ))
        certificate_result = None
        certificate_row = None

        if certificate_id:
            certificate_result = yield self.db.runQuery("SELECT row_id FROM claim_cache "
                                                        "WHERE claim_id=?", (certificate_id, ))
        if certificate_id is not None and certificate_result is None:
            log.warning("Certificate is not in cache")
        elif certificate_result:
            certificate_row = certificate_result[0][0]

        if result:
            cache_row, ts = result[0]
            yield self.db.runOperation("INSERT OR REPLACE INTO uri_cache(uri, cache_row, "
                                       "                      certificate_row, last_modified) "
                                       "VALUES (?, ?, ?, ?)",
                                       (uri, cache_row, certificate_row,
                                       str(int(time.time()))))
        else:
            log.warning("Claim is not in cache")
        defer.returnValue(None)

    @rerun_if_locked
    @defer.inlineCallbacks
    def get_cached_claim_for_uri(self, uri, check_expire=True):
        result = yield self.db.runQuery("SELECT "
                                        "claim.claim_id, cert.claim_id, uri_cache.last_modified "
                                        "FROM uri_cache "
                                        "INNER JOIN claim_cache as claim "
                                        "ON uri_cache.cache_row=claim.row_id "
                                        "LEFT OUTER JOIN claim_cache as cert "
                                        "ON uri_cache.certificate_row=cert.row_id "
                                        "WHERE uri_cache.uri=?", (uri, ))
        response = None
        if result:
            claim_id, certificate_id, last_modified = result[0]
            last_modified = int(last_modified)
            if check_expire and time.time() - last_modified > conf.settings['cache_time']:
                defer.returnValue(None)
            claim = yield self.get_cached_claim(claim_id)
            if claim:
                response = {
                    "claim": claim
                }
            if response and certificate_id is not None:
                certificate = yield self.get_cached_claim(certificate_id)
                response['certificate'] = certificate
        defer.returnValue(response)


class Wallet(object):
    """This class implements the Wallet interface for the LBRYcrd payment system"""
    implements(IWallet)

    def __init__(self, storage):
        if not isinstance(storage, MetaDataStorage):
            raise ValueError('storage must be an instance of MetaDataStorage')
        self._storage = storage
        self.next_manage_call = None
        self.wallet_balance = Decimal(0.0)
        self.total_reserved_points = Decimal(0.0)
        self.peer_addresses = {}  # {Peer: string}
        self.queued_payments = defaultdict(Decimal)  # {address(string): amount(Decimal)}
        self.expected_balances = defaultdict(Decimal)  # {address(string): amount(Decimal)}
        self.current_address_given_to_peer = {}  # {Peer: address(string)}
        # (Peer, address(string), amount(Decimal), time(datetime), count(int),
        # incremental_amount(float))
        self.expected_balance_at_time = deque()
        self.max_expected_payment_time = datetime.timedelta(minutes=3)
        self.stopped = True

        self.manage_running = False
        self._manage_count = 0
        self._balance_refresh_time = 3
        self._batch_count = 20

    def start(self):
        log.info("Starting wallet.")
        def start_manage():
            self.stopped = False
            self.manage()
            return True

        d = self._storage.load()
        d.addCallback(lambda _: self._start())
        d.addCallback(lambda _: start_manage())
        return d

    def _save_name_metadata(self, name, claim_outpoint, sd_hash):
        return self._storage.save_name_metadata(name, claim_outpoint, sd_hash)

    def _get_claim_metadata_for_sd_hash(self, sd_hash):
        return self._storage.get_claim_metadata_for_sd_hash(sd_hash)

    def _update_claimid(self, claim_id, name, claim_outpoint):
        return self._storage.update_claimid(claim_id, name, claim_outpoint)

    @staticmethod
    def log_stop_error(err):
        log.error("An error occurred stopping the wallet: %s", err.getTraceback())

    def stop(self):
        log.info("Stopping wallet.")
        self.stopped = True
        # If self.next_manage_call is None, then manage is currently running or else
        # start has not been called, so set stopped and do nothing else.
        if self.next_manage_call is not None:
            self.next_manage_call.cancel()
            self.next_manage_call = None

        d = self.manage(do_full=True)
        d.addErrback(self.log_stop_error)
        d.addCallback(lambda _: self._stop())
        d.addErrback(self.log_stop_error)
        return d

    def manage(self, do_full=False):
        self.next_manage_call = None
        have_set_manage_running = [False]
        self._manage_count += 1
        if self._manage_count % self._batch_count == 0:
            self._manage_count = 0
            do_full = True

        def check_if_manage_running():

            d = defer.Deferred()

            def fire_if_not_running():
                if self.manage_running is False:
                    self.manage_running = True
                    have_set_manage_running[0] = True
                    d.callback(True)
                elif do_full is False:
                    d.callback(False)
                else:
                    task.deferLater(reactor, 1, fire_if_not_running)

            fire_if_not_running()
            return d

        d = check_if_manage_running()

        def do_manage():
            if do_full:
                d = self._check_expected_balances()
                d.addCallback(lambda _: self._send_payments())
            else:
                d = defer.succeed(True)

            def log_error(err):
                if isinstance(err, AttributeError):
                    log.warning("Failed to get an updated balance")
                    log.warning("Last balance update: %s", str(self.wallet_balance))

            d.addCallbacks(lambda _: self.update_balance(), log_error)
            return d

        d.addCallback(lambda should_run: do_manage() if should_run else None)

        def set_next_manage_call():
            if not self.stopped:
                self.next_manage_call = reactor.callLater(self._balance_refresh_time, self.manage)

        d.addCallback(lambda _: set_next_manage_call())

        def log_error(err):
            log.error("Something went wrong during manage. Error message: %s",
                      err.getErrorMessage())
            return err

        d.addErrback(log_error)

        def set_manage_not_running(arg):
            if have_set_manage_running[0] is True:
                self.manage_running = False
            return arg

        d.addBoth(set_manage_not_running)
        return d

    @defer.inlineCallbacks
    def update_balance(self):
        """ obtain balance from lbryum wallet and set self.wallet_balance
        """
        balance = yield self._update_balance()
        if self.wallet_balance != balance:
            log.debug("Got a new balance: %s", balance)
        self.wallet_balance = balance

    def get_info_exchanger(self):
        return LBRYcrdAddressRequester(self)

    def get_wallet_info_query_handler_factory(self):
        return LBRYcrdAddressQueryHandlerFactory(self)

    def reserve_points(self, identifier, amount):
        """Ensure a certain amount of points are available to be sent as
        payment, before the service is rendered

        @param identifier: The peer to which the payment will ultimately be sent

        @param amount: The amount of points to reserve

        @return: A ReservedPoints object which is given to send_points
            once the service has been rendered
        """
        rounded_amount = Decimal(str(round(amount, 8)))
        if rounded_amount < 0:
            raise NegativeFundsError(rounded_amount)
        if self.get_balance() >= rounded_amount:
            self.total_reserved_points += rounded_amount
            return ReservedPoints(identifier, rounded_amount)
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
        rounded_amount = Decimal(str(round(amount, 8)))
        peer = reserved_points.identifier
        assert rounded_amount <= reserved_points.amount
        assert peer in self.peer_addresses
        self.queued_payments[self.peer_addresses[peer]] += rounded_amount
        # make any unused points available
        self.total_reserved_points -= (reserved_points.amount - rounded_amount)
        log.debug("ordering that %s points be sent to %s", str(rounded_amount),
                  str(self.peer_addresses[peer]))
        peer.update_stats('points_sent', amount)
        return defer.succeed(True)

    def send_points_to_address(self, reserved_points, amount):
        """
        Schedule a payment to be sent to an address

        @param reserved_points: ReservedPoints object previously returned by reserve_points

        @param amount: amount of points to actually send. must be less than or equal to the
            amount reselved in reserved_points

        @return: Deferred which fires when the payment has been scheduled
        """
        rounded_amount = Decimal(str(round(amount, 8)))
        address = reserved_points.identifier
        assert rounded_amount <= reserved_points.amount
        self.queued_payments[address] += rounded_amount
        self.total_reserved_points -= (reserved_points.amount - rounded_amount)
        log.debug("Ordering that %s points be sent to %s", str(rounded_amount),
                  str(address))
        return defer.succeed(True)

    def add_expected_payment(self, peer, amount):
        """Increase the number of points expected to be paid by a peer"""
        rounded_amount = Decimal(str(round(amount, 8)))
        assert peer in self.current_address_given_to_peer
        address = self.current_address_given_to_peer[peer]
        log.debug("expecting a payment at address %s in the amount of %s",
                  str(address), str(rounded_amount))
        self.expected_balances[address] += rounded_amount
        expected_balance = self.expected_balances[address]
        expected_time = datetime.datetime.now() + self.max_expected_payment_time
        self.expected_balance_at_time.append(
            (peer, address, expected_balance, expected_time, 0, amount))
        peer.update_stats('expected_points', amount)

    def update_peer_address(self, peer, address):
        self.peer_addresses[peer] = address

    def get_unused_address_for_peer(self, peer):
        def set_address_for_peer(address):
            self.current_address_given_to_peer[peer] = address
            return address

        d = self.get_unused_address()
        d.addCallback(set_address_for_peer)
        return d

    def _send_payments(self):
        payments_to_send = {}
        for address, points in self.queued_payments.items():
            if points > 0:
                log.debug("Should be sending %s points to %s", str(points), str(address))
                payments_to_send[address] = points
                self.total_reserved_points -= points
            else:
                log.info("Skipping dust")

            del self.queued_payments[address]

        if payments_to_send:
            log.debug("Creating a transaction with outputs %s", str(payments_to_send))
            d = self._do_send_many(payments_to_send)
            d.addCallback(lambda txid: log.debug("Sent transaction %s", txid))
            return d

        log.debug("There were no payments to send")
        return defer.succeed(True)

    ######

    @defer.inlineCallbacks
    def get_cached_claim(self, claim_id, check_expire=True):
        results = yield self._storage.get_cached_claim(claim_id, check_expire)
        defer.returnValue(results)

    @defer.inlineCallbacks
    def get_claim_by_claim_id(self, claim_id, check_expire=True):
        cached_claim = yield self.get_cached_claim(claim_id, check_expire)
        if cached_claim:
            result = cached_claim
        else:
            log.debug("Refreshing cached claim: %s", claim_id)
            claim = yield self._get_claim_by_claimid(claim_id)
            try:
                result = yield self._handle_claim_result(claim)
            except (UnknownNameError, UnknownClaimID, UnknownURI) as err:
                result = {'error': err.message}

        defer.returnValue(result)

    @defer.inlineCallbacks
    def get_claimid(self, txid, nout):
        claim_outpoint = ClaimOutpoint(txid, nout)
        claim_id = yield self._storage.get_claimid_for_tx(claim_outpoint)
        defer.returnValue(claim_id)

    @defer.inlineCallbacks
    def get_my_claim(self, name):
        my_claims = yield self.get_name_claims()
        my_claim = False
        for claim in my_claims:
            if claim['name'] == name:
                claim['value'] = ClaimDict.load_dict(claim['value'])
                my_claim = claim
                break
        defer.returnValue(my_claim)

    @defer.inlineCallbacks
    def _decode_and_cache_claim_result(self, claim, update_caches):
        if 'has_signature' in claim and claim['has_signature']:
            if not claim['signature_is_valid']:
                log.warning("lbry://%s#%s has an invalid signature",
                            claim['name'], claim['claim_id'])
        try:
            decoded = smart_decode(claim['value'])
            claim_dict = decoded.claim_dict
            outpoint = ClaimOutpoint(claim['txid'], claim['nout'])
            name = claim['name']
            claim['value'] = claim_dict
            claim['hex'] = decoded.serialized.encode('hex')
            if update_caches:
                if decoded.is_stream:
                    yield self._save_name_metadata(name, outpoint, decoded.source_hash)
                yield self._update_claimid(claim['claim_id'], name, outpoint)
                yield self._storage.save_claim_to_cache(claim['claim_id'],
                                                        claim['claim_sequence'],
                                                        decoded, claim['address'],
                                                        claim['height'],
                                                        claim['amount'], claim['supports'],
                                                        claim.get('channel_name', None),
                                                        claim.get('signature_is_valid', None))
        except DecodeError:
            claim['hex'] = claim['value']
            claim['value'] = None
            claim['error'] = "Failed to decode value"

        defer.returnValue(claim)



    @defer.inlineCallbacks
    def _handle_claim_result(self, results, update_caches=True):
        if not results:
            #TODO: cannot determine what name we searched for here
            # we should fix lbryum commands that return None
            raise UnknownNameError("")

        if 'error' in results:
            if results['error'] in ['name is not claimed', 'claim not found']:
                if 'claim_id' in results:
                    raise UnknownClaimID(results['claim_id'])
                elif 'name' in results:
                    raise UnknownNameError(results['name'])
                elif 'uri' in results:
                    raise UnknownURI(results['uri'])
                elif 'outpoint' in results:
                    raise UnknownOutpoint(results['outpoint'])
            raise Exception(results['error'])

        # case where return value is {'certificate':{'txid', 'value',...},...}
        if 'certificate' in results:
            results['certificate'] = yield self._decode_and_cache_claim_result(
                                                                        results['certificate'],
                                                                        update_caches)

        # case where return value is {'claim':{'txid','value',...},...}
        if 'claim' in results:
            results['claim'] = yield self._decode_and_cache_claim_result(
                                                                     results['claim'],
                                                                     update_caches)

        # case where return value is {'txid','value',...}
        # returned by queries that are not name resolve related
        # (getclaimbyoutpoint, getclaimbyid, getclaimsfromtx)
        # we do not update caches here because it should be missing
        # some values such as claim_sequence, and supports
        elif 'value' in results:
            results = yield self._decode_and_cache_claim_result(results, update_caches=False)

        # case where there is no 'certificate', 'value', or 'claim' key
        elif 'certificate' not in results:
            msg = 'result in unexpected format:{}'.format(results)
            assert False, msg

        defer.returnValue(results)

    @defer.inlineCallbacks
    def resolve(self, *uris, **kwargs):
        check_cache = kwargs.get('check_cache', True)
        page = kwargs.get('page', 0)
        page_size = kwargs.get('page_size', 10)

        result = {}
        needed = []
        for uri in uris:
            cached_claim = None
            if check_cache:
                cached_claim = yield self._storage.get_cached_claim_for_uri(uri, check_cache)
            if cached_claim:
                log.debug("Using cached results for %s", uri)
                result[uri] = yield self._handle_claim_result(cached_claim, update_caches=False)
            else:
                log.info("Resolving %s", uri)
                needed.append(uri)

        batch_results = yield self._get_values_for_uris(page, page_size, *uris)

        for uri, resolve_results in batch_results.iteritems():
            claim_id = None
            if resolve_results and 'claim' in resolve_results:
                claim_id = resolve_results['claim']['claim_id']
            certificate_id = None
            if resolve_results and 'certificate' in resolve_results:
                certificate_id = resolve_results['certificate']['claim_id']
            try:
                result[uri] = yield self._handle_claim_result(resolve_results, update_caches=True)
                if claim_id:
                    yield self._storage.save_claim_to_uri_cache(uri, claim_id, certificate_id)
            except (UnknownNameError, UnknownClaimID, UnknownURI) as err:
                result[uri] = {'error': err.message}

        defer.returnValue(result)

    @defer.inlineCallbacks
    def get_claim_by_outpoint(self, claim_outpoint, check_expire=True):
        claim_id = yield self._storage.get_claimid_for_tx(claim_outpoint)
        txid, nout = claim_outpoint['txid'], claim_outpoint['nout']
        if claim_id:
            cached_claim = yield self._storage.get_cached_claim(claim_id, check_expire)
        else:
            cached_claim = None
        if not cached_claim:
            claim = yield self._get_claim_by_outpoint(txid, nout)
            try:
                result = yield self._handle_claim_result(claim)
            except (UnknownOutpoint) as err:
                result = {'error': err.message}
        else:
            result = cached_claim
        defer.returnValue(result)

    @defer.inlineCallbacks
    def get_claim_by_name(self, name):
        get_name_result = yield self._get_value_for_name(name)
        result = yield self._handle_claim_result(get_name_result)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def get_claims_for_name(self, name):
        result = yield self._get_claims_for_name(name)
        claims = result['claims']
        claims_for_return = []
        for claim in claims:
            try:
                decoded = smart_decode(claim['value'])
                claim['value'] = decoded.claim_dict
                claim['hex'] = decoded.serialized.encode('hex')
                claims_for_return.append(claim)
            except DecodeError:
                claim['hex'] = claim['value']
                claim['value'] = None
                claim['error'] = "Failed to decode"
                log.warning("Failed to decode claim value for lbry://%s#%s", claim['name'],
                            claim['claim_id'])
                claims_for_return.append(claim)

        result['claims'] = claims_for_return
        defer.returnValue(result)

    def _process_claim_out(self, claim_out):
        claim_out.pop('success')
        claim_out['fee'] = float(claim_out['fee'])
        return claim_out

    def claim_new_channel(self, channel_name, amount):
        parsed_channel_name = parse_lbry_uri(channel_name)
        if not parsed_channel_name.is_channel:
            raise Exception("Invalid channel name")
        elif (parsed_channel_name.path or parsed_channel_name.claim_id or
              parsed_channel_name.bid_position or parsed_channel_name.claim_sequence):
            raise Exception("New channel claim should have no fields other than name")
        log.info("Preparing to make certificate claim for %s", channel_name)
        return self._claim_certificate(parsed_channel_name.name, amount)

    @defer.inlineCallbacks
    def channel_list(self):
        certificates = yield self._get_certificate_claims()
        results = []
        for claim in certificates:
            formatted = yield self._handle_claim_result(claim)
            results.append(formatted)
        defer.returnValue(results)

    @defer.inlineCallbacks
    def claim_name(self, name, bid, metadata, certificate_id=None, claim_address=None,
                   change_address=None):
        """
        Claim a name, or update if name already claimed by user

        @param name: str, name to claim
        @param bid: float, bid amount
        @param metadata: ClaimDict compliant dict
        @param certificate_id: str (optional), claim id of channel certificate
        @param claim_address: str (optional), address to send claim to
        @param change_address: str (optional), address to send change

        @return: Deferred which returns a dict containing below items
            txid - txid of the resulting transaction
            nout - nout of the resulting claim
            fee - transaction fee paid to make claim
            claim_id -  claim id of the claim
        """

        decoded = ClaimDict.load_dict(metadata)
        serialized = decoded.serialized

        if self.get_balance() < Decimal(bid):
            raise InsufficientFundsError()

        claim = yield self._send_name_claim(name, serialized.encode('hex'),
                                            bid, certificate_id, claim_address, change_address)

        if not claim['success']:
            msg = 'Claim to name {} failed: {}'.format(name, claim['reason'])
            raise Exception(msg)

        claim = self._process_claim_out(claim)
        claim_outpoint = ClaimOutpoint(claim['txid'], claim['nout'])
        log.info("Saving metadata for claim %s %d", claim['txid'], claim['nout'])
        yield self._update_claimid(claim['claim_id'], name, claim_outpoint)
        yield self._save_name_metadata(name, claim_outpoint, decoded.source_hash)
        defer.returnValue(claim)

    @defer.inlineCallbacks
    def abandon_claim(self, claim_id):
        claim_out = yield self._abandon_claim(claim_id)

        if not claim_out['success']:
            msg = 'Abandon of {} failed: {}'.format(claim_id, claim_out['reason'])
            raise Exception(msg)

        claim_out = self._process_claim_out(claim_out)
        defer.returnValue(claim_out)

    def support_claim(self, name, claim_id, amount):
        def _parse_support_claim_out(claim_out):
            if not claim_out['success']:
                msg = 'Support of {}:{} failed: {}'.format(name, claim_id, claim_out['reason'])
                raise Exception(msg)
            claim_out = self._process_claim_out(claim_out)
            return defer.succeed(claim_out)

        if self.get_balance() < amount:
            raise InsufficientFundsError()

        d = self._support_claim(name, claim_id, amount)
        d.addCallback(lambda claim_out: _parse_support_claim_out(claim_out))
        return d

    def get_block_info(self, height):
        d = self._get_blockhash(height)
        return d

    def get_history(self):
        d = self._get_history()
        return d

    def address_is_mine(self, address):
        d = self._address_is_mine(address)
        return d

    def get_transaction(self, txid):
        d = self._get_transaction(txid)
        return d

    def get_claim_metadata_for_sd_hash(self, sd_hash):
        return self._get_claim_metadata_for_sd_hash(sd_hash)

    def get_balance(self):
        return self.wallet_balance - self.total_reserved_points - sum(self.queued_payments.values())

    def _check_expected_balances(self):
        now = datetime.datetime.now()
        balances_to_check = []
        try:
            while self.expected_balance_at_time[0][3] < now:
                balances_to_check.append(self.expected_balance_at_time.popleft())
        except IndexError:
            pass
        ds = []
        for balance_to_check in balances_to_check:
            log.debug("Checking balance of address %s", str(balance_to_check[1]))
            d = self._get_balance_for_address(balance_to_check[1])
            d.addCallback(lambda bal: bal >= balance_to_check[2])
            ds.append(d)
        dl = defer.DeferredList(ds)

        def handle_checks(results):
            from future_builtins import zip
            for balance, (success, result) in zip(balances_to_check, results):
                peer = balance[0]
                if success is True:
                    if result is False:
                        if balance[4] <= 1:  # first or second strike, give them another chance
                            new_expected_balance = (
                                balance[0],
                                balance[1],
                                balance[2],
                                datetime.datetime.now() + self.max_expected_payment_time,
                                balance[4] + 1,
                                balance[5]
                            )
                            self.expected_balance_at_time.append(new_expected_balance)
                            peer.update_score(-5.0)
                        else:
                            peer.update_score(-50.0)
                    else:
                        if balance[4] == 0:
                            peer.update_score(balance[5])
                        peer.update_stats('points_received', balance[5])
                else:
                    log.warning("Something went wrong checking a balance. Peer: %s, account: %s,"
                                "expected balance: %s, expected time: %s, count: %s, error: %s",
                                str(balance[0]), str(balance[1]), str(balance[2]), str(balance[3]),
                                str(balance[4]), str(result.getErrorMessage()))

        dl.addCallback(handle_checks)
        return dl

    # ======== Must be overridden ======== #

    def _update_balance(self):
        return defer.fail(NotImplementedError())

    def get_new_address(self):
        return defer.fail(NotImplementedError())

    def get_address_balance(self, address):
        return defer.fail(NotImplementedError())

    def get_block(self, blockhash):
        return defer.fail(NotImplementedError())

    def get_most_recent_blocktime(self):
        return defer.fail(NotImplementedError())

    def get_best_blockhash(self):
        return defer.fail(NotImplementedError())

    def get_name_claims(self):
        return defer.fail(NotImplementedError())

    def _get_claims_for_name(self, name):
        return defer.fail(NotImplementedError())

    def _claim_certificate(self, name, amount):
        return defer.fail(NotImplementedError())

    def _send_name_claim(self, name, val, amount, certificate_id=None, claim_address=None,
                         change_address=None):
        return defer.fail(NotImplementedError())

    def _abandon_claim(self, claim_id):
        return defer.fail(NotImplementedError())

    def _support_claim(self, name, claim_id, amount):
        return defer.fail(NotImplementedError())

    def _do_send_many(self, payments_to_send):
        return defer.fail(NotImplementedError())

    def _get_value_for_name(self, name):
        return defer.fail(NotImplementedError())

    def get_claims_from_tx(self, txid):
        return defer.fail(NotImplementedError())

    def _get_balance_for_address(self, address):
        return defer.fail(NotImplementedError())

    def _get_history(self):
        return defer.fail(NotImplementedError())

    def _address_is_mine(self, address):
        return defer.fail(NotImplementedError())

    def _get_value_for_uri(self, uri):
        return defer.fail(NotImplementedError())

    def _get_certificate_claims(self):
        return defer.fail(NotImplementedError())

    def _get_claim_by_outpoint(self, txid, nout):
        return defer.fail(NotImplementedError())

    def _get_claim_by_claimid(self, claim_id):
        return defer.fail(NotImplementedError())

    def _get_values_for_uris(self, page, page_size, *uris):
        return defer.fail(NotImplementedError())

    def send_claim_to_address(self, claim_id, destination, amount):
        return defer.fail(NotImplementedError())

    def _start(self):
        pass

    def _stop(self):
        pass


class LBRYumWallet(Wallet):
    def __init__(self, storage, config=None):
        Wallet.__init__(self, storage)
        self._config = config
        self.config = make_config(self._config)
        self.network = None
        self.wallet = None
        self.is_first_run = False
        self.printed_retrieving_headers = False
        self._start_check = None
        self._catch_up_check = None
        self._caught_up_counter = 0
        self._lag_counter = 0
        self.blocks_behind = 0
        self.catchup_progress = 0

    def _is_first_run(self):
        return (not self.printed_retrieving_headers and
                self.network.blockchain.retrieving_headers)

    def _start(self):
        network_start_d = defer.Deferred()

        def setup_network():
            self.network = Network(self.config)
            log.info("Loading the wallet")
            return defer.succeed(self.network.start())

        def check_started():
            if self.network.is_connecting():
                if self._is_first_run():
                    log.info("Running the wallet for the first time. This may take a moment.")
                    self.printed_retrieving_headers = True
                return False
            self._start_check.stop()
            self._start_check = None
            if self.network.is_connected():
                network_start_d.callback(True)
            else:
                network_start_d.errback(ValueError("Failed to connect to network."))

        self._start_check = task.LoopingCall(check_started)

        d = setup_network()
        d.addCallback(lambda _: self._load_wallet())
        d.addCallback(self._save_wallet)
        d.addCallback(lambda _: self._start_check.start(.1))
        d.addCallback(lambda _: network_start_d)
        d.addCallback(lambda _: self._load_blockchain())
        d.addCallback(lambda _: log.info("Subscribing to addresses"))
        d.addCallback(lambda _: self.wallet.wait_until_synchronized(lambda _: None))
        d.addCallback(lambda _: log.info("Synchronized wallet"))
        return d

    def _stop(self):
        if self._start_check is not None:
            self._start_check.stop()
            self._start_check = None

        if self._catch_up_check is not None:
            if self._catch_up_check.running:
                self._catch_up_check.stop()
            self._catch_up_check = None

        d = defer.Deferred()

        def check_stopped():
            if self.network:
                if self.network.is_connected():
                    return False
            stop_check.stop()
            self.network = None
            d.callback(True)

        if self.wallet:
            self.wallet.stop_threads()
            log.info("Stopped wallet")
        if self.network:
            self.network.stop()
            log.info("Stopped connection to lbryum server")

        stop_check = task.LoopingCall(check_stopped)
        stop_check.start(.1)
        return d

    def _load_wallet(self):
        path = self.config.get_wallet_path()
        storage = lbryum.wallet.WalletStorage(path)
        wallet = lbryum.wallet.Wallet(storage)
        if not storage.file_exists:
            self.is_first_run = True
            seed = wallet.make_seed()
            wallet.add_seed(seed, None)
            wallet.create_master_keys(None)
            wallet.create_main_account()
            wallet.synchronize()
        self.wallet = wallet
        self._check_large_wallet()
        return defer.succeed(True)

    def _check_large_wallet(self):
        if len(self.wallet.addresses(include_change=False)) > 1000:
            log.warning(("Your wallet is excessively large, please follow instructions here: ",
                         "https://github.com/lbryio/lbry/issues/437 to reduce your wallet size"))

    def _load_blockchain(self):
        blockchain_caught_d = defer.Deferred()

        def on_update_callback(event, *args):
            # This callback is called by lbryum when something chain
            # related has happened
            local_height = self.network.get_local_height()
            remote_height = self.network.get_server_height()
            updated_blocks_behind = self.network.get_blocks_behind()
            log.info(
                'Local Height: %s, remote height: %s, behind: %s',
                local_height, remote_height, updated_blocks_behind)

            self.blocks_behind = updated_blocks_behind
            if local_height != remote_height:
                return

            assert self.blocks_behind == 0
            self.network.unregister_callback(on_update_callback)
            log.info("Wallet Loaded")
            reactor.callFromThread(blockchain_caught_d.callback, True)

        self.network.register_callback(on_update_callback, ['updated'])

        d = defer.succeed(self.wallet.start_threads(self.network))
        d.addCallback(lambda _: blockchain_caught_d)
        return d

    def _get_cmd_runner(self):
        return Commands(self.config, self.wallet, self.network)

    # run commands as a defer.succeed,
    # lbryum commands should be run this way , unless if the command
    # only makes a lbrum server query, use _run_cmd_as_defer_to_thread()
    def _run_cmd_as_defer_succeed(self, command_name, *args, **kwargs):
        cmd_runner = self._get_cmd_runner()
        cmd = known_commands[command_name]
        func = getattr(cmd_runner, cmd.name)
        return defer.succeed(func(*args, **kwargs))

    # run commands as a deferToThread,  lbryum commands that only make
    # queries to lbryum server should be run this way
    # TODO: keep track of running threads and cancel them on `stop`
    #       otherwise the application will hang, waiting for threads to complete
    def _run_cmd_as_defer_to_thread(self, command_name, *args, **kwargs):
        cmd_runner = self._get_cmd_runner()
        cmd = known_commands[command_name]
        func = getattr(cmd_runner, cmd.name)
        return threads.deferToThread(func, *args, **kwargs)

    def _update_balance(self):
        accounts = None
        exclude_claimtrietx = True
        d = self._run_cmd_as_defer_succeed('getbalance', accounts, exclude_claimtrietx)
        d.addCallback(
            lambda result: Decimal(result['confirmed']) + Decimal(result.get('unconfirmed', 0.0)))
        return d

    # Always create and return a brand new address
    @defer.inlineCallbacks
    def get_new_address(self):
        addr = self.wallet.create_new_address(account=None)
        yield self._save_wallet()
        defer.returnValue(addr)

    # Get the balance of a given address.

    def get_address_balance(self, address, include_balance=False):
        c, u, x = self.wallet.get_addr_balance(address)
        if include_balance is False:
            return Decimal(float(c) / COIN)
        else:
            return Decimal((float(c) + float(u) + float(x)) / COIN)


    # Return an address with no balance in it, if
    # there is none, create a brand new address
    @defer.inlineCallbacks
    def get_unused_address(self):
        addr = self.wallet.get_unused_address(account=None)
        if addr is None:
            addr = self.wallet.create_new_address()
        yield self._save_wallet()
        defer.returnValue(addr)

    def get_block(self, blockhash):
        return self._run_cmd_as_defer_to_thread('getblock', blockhash)

    def get_most_recent_blocktime(self):
        height = self.network.get_local_height()
        if height < 0:
            return defer.succeed(None)
        header = self.network.get_header(self.network.get_local_height())
        return defer.succeed(header['timestamp'])

    def get_best_blockhash(self):
        height = self.network.get_local_height()
        if height < 0:
            return defer.succeed(None)
        header = self.network.blockchain.read_header(height)
        return defer.succeed(self.network.blockchain.hash_header(header))

    def _get_blockhash(self, height):
        header = self.network.blockchain.read_header(height)
        return defer.succeed(self.network.blockchain.hash_header(header))

    def _get_transaction(self, txid):
        return self._run_cmd_as_defer_to_thread("gettransaction", txid)

    def get_name_claims(self):
        return self._run_cmd_as_defer_succeed('getnameclaims')

    def _get_claims_for_name(self, name):
        return self._run_cmd_as_defer_to_thread('getclaimsforname', name)

    @defer.inlineCallbacks
    def _send_name_claim(self, name, value, amount,
                            certificate_id=None, claim_address=None, change_address=None):
        log.info("Send claim: %s for %s: %s ", name, amount, value)
        claim_out = yield self._run_cmd_as_defer_succeed('claim', name, value, amount,
                                                         certificate_id=certificate_id,
                                                         claim_addr=claim_address,
                                                         change_addr=change_address)
        defer.returnValue(claim_out)

    @defer.inlineCallbacks
    def _abandon_claim(self, claim_id):
        log.debug("Abandon %s" % claim_id)
        tx_out = yield self._run_cmd_as_defer_succeed('abandon', claim_id)
        defer.returnValue(tx_out)

    @defer.inlineCallbacks
    def _support_claim(self, name, claim_id, amount):
        log.debug("Support %s %s %f" % (name, claim_id, amount))
        broadcast = False
        tx = yield self._run_cmd_as_defer_succeed('support', name, claim_id, amount, broadcast)
        claim_out = yield self._broadcast_claim_transaction(tx)
        defer.returnValue(claim_out)

    @defer.inlineCallbacks
    def _broadcast_claim_transaction(self, claim_out):
        if 'success' not in claim_out:
            raise Exception('Unexpected claim command output: {}'.format(claim_out))
        if claim_out['success']:
            yield self._broadcast_transaction(claim_out['tx'])
        defer.returnValue(claim_out)

    @defer.inlineCallbacks
    def _broadcast_transaction(self, raw_tx):
        txid = yield self._run_cmd_as_defer_succeed('broadcast', raw_tx)
        log.info("Broadcast tx: %s", txid)
        if len(txid) != 64:
            raise Exception("Transaction rejected. Raw tx: {}".format(raw_tx))
        defer.returnValue(txid)

    def _do_send_many(self, payments_to_send):
        def broadcast_send_many(paytomany_out):
            if 'hex' not in paytomany_out:
                raise Exception('Unexpected paytomany output:{}'.format(paytomany_out))
            return self._broadcast_transaction(paytomany_out['hex'])

        log.debug("Doing send many. payments to send: %s", str(payments_to_send))
        d = self._run_cmd_as_defer_succeed('paytomany', payments_to_send.iteritems())
        d.addCallback(lambda out: broadcast_send_many(out))
        return d

    def _get_value_for_name(self, name):
        if not name:
            raise Exception("No name given")
        return self._run_cmd_as_defer_to_thread('getvalueforname', name)

    def _get_value_for_uri(self, uri):
        if not uri:
            raise Exception("No uri given")
        return self._run_cmd_as_defer_to_thread('getvalueforuri', uri)

    def _get_values_for_uris(self, page, page_size, *uris):
        return self._run_cmd_as_defer_to_thread('getvaluesforuris', False, page, page_size,
                                                *uris)

    def _claim_certificate(self, name, amount):
        return self._run_cmd_as_defer_succeed('claimcertificate', name, amount)

    def _get_certificate_claims(self):
        return self._run_cmd_as_defer_succeed('getcertificateclaims')

    def get_claims_from_tx(self, txid):
        return self._run_cmd_as_defer_to_thread('getclaimsfromtx', txid)

    def _get_claim_by_outpoint(self, txid, nout):
        return self._run_cmd_as_defer_to_thread('getclaimbyoutpoint', txid, nout)

    def _get_claim_by_claimid(self, claim_id):
        return self._run_cmd_as_defer_to_thread('getclaimbyid', claim_id)

    def _get_balance_for_address(self, address):
        return defer.succeed(Decimal(self.wallet.get_addr_received(address)) / COIN)

    def get_nametrie(self):
        return self._run_cmd_as_defer_to_thread('getclaimtrie')

    def _get_history(self):
        return self._run_cmd_as_defer_succeed('history')

    def _address_is_mine(self, address):
        return self._run_cmd_as_defer_succeed('ismine', address)

    # returns a list of public keys associated with address
    # (could be multiple public keys if a multisig address)
    def get_pub_keys(self, address):
        return self._run_cmd_as_defer_succeed('getpubkeys', address)

    def list_addresses(self):
        return self._run_cmd_as_defer_succeed('listaddresses')

    def send_claim_to_address(self, claim_id, destination, amount):
        return self._run_cmd_as_defer_succeed('sendclaimtoaddress', claim_id, destination, amount)

    def _save_wallet(self, val=None):
        self.wallet.storage.write()
        return defer.succeed(val)


class LBRYcrdAddressRequester(object):
    implements([IRequestCreator])

    def __init__(self, wallet):
        self.wallet = wallet
        self._protocols = []

    # ======== IRequestCreator ======== #

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

    # ======== internal calls ======== #

    def _handle_address_response(self, response_dict, peer, request, protocol):
        if request.response_identifier not in response_dict:
            raise ValueError(
                "Expected {} in response but did not get it".format(request.response_identifier))
        assert protocol in self._protocols, "Responding protocol is not in our list of protocols"
        address = response_dict[request.response_identifier]
        self.wallet.update_peer_address(peer, address)

    def _request_failed(self, err, peer):
        if not err.check(RequestCanceledError):
            log.warning("A peer failed to send a valid public key response. Error: %s, peer: %s",
                        err.getErrorMessage(), str(peer))
            return err


class LBRYcrdAddressQueryHandlerFactory(object):
    implements(IQueryHandlerFactory)

    def __init__(self, wallet):
        self.wallet = wallet

    # ======== IQueryHandlerFactory ======== #

    def build_query_handler(self):
        q_h = LBRYcrdAddressQueryHandler(self.wallet)
        return q_h

    def get_primary_query_identifier(self):
        return 'lbrycrd_address'

    def get_description(self):
        return "LBRYcrd Address - an address for receiving payments via LBRYcrd"


class LBRYcrdAddressQueryHandler(object):
    implements(IQueryHandler)

    def __init__(self, wallet):
        self.wallet = wallet
        self.query_identifiers = ['lbrycrd_address']
        self.address = None
        self.peer = None

    # ======== IQueryHandler ======== #

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
            log.warning("Expected a request for an address, but did not receive one")
            return defer.fail(
                Failure(ValueError("Expected but did not receive an address request")))
        else:
            return defer.succeed({})


def make_config(config=None):
    if config is None:
        config = {}
    return SimpleConfig(config) if isinstance(config, dict) else config
