import datetime
import logging
import os

from twisted.internet import threads, reactor, defer, task
from twisted.python.failure import Failure
from twisted.enterprise import adbapi
from collections import defaultdict, deque
from zope.interface import implements
from decimal import Decimal

from lbryum import SimpleConfig, Network
from lbryum.lbrycrd import COIN
import lbryum.wallet
from lbryum.commands import known_commands, Commands

from lbryschema.uri import parse_lbry_uri
from lbryschema.claim import ClaimDict
from lbryschema.error import DecodeError
from lbryschema.decode import smart_decode

from lbrynet.core.sqlite_helpers import rerun_if_locked
from lbrynet.interfaces import IRequestCreator, IQueryHandlerFactory, IQueryHandler, IWallet
from lbrynet.core.client.ClientRequest import ClientRequest
from lbrynet.core.Error import RequestCanceledError, InsufficientFundsError, UnknownNameError
from lbrynet.db_migrator.migrate1to2 import UNSET_NOUT

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


class MetaDataStorage(object):
    def load(self):
        return defer.succeed(True)

    def clean_bad_records(self):
        return defer.succeed(True)

    def save_name_metadata(self, name, claim_outpoint, sd_hash):
        return defer.succeed(True)

    def get_claim_metadata_for_sd_hash(self, sd_hash):
        return defer.succeed(True)

    def update_claimid(self, claim_id, name, claim_outpoint):
        return defer.succeed(True)

    def get_claimid_for_tx(self, name, claim_outpoint):
        return defer.succeed(True)


class InMemoryStorage(MetaDataStorage):
    def __init__(self):
        self.metadata = {}
        self.claimids = {}
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

    def get_claimid_for_tx(self, name, claim_outpoint):
        try:
            return defer.succeed(
                self.claimids[(name, claim_outpoint['txid'], claim_outpoint['nout'])])
        except KeyError:
            return defer.succeed(None)


class SqliteStorage(MetaDataStorage):
    def __init__(self, db_dir):
        self.db_dir = db_dir
        self.db = None
        MetaDataStorage.__init__(self)

    def load(self):
        self.db = adbapi.ConnectionPool('sqlite3', os.path.join(self.db_dir, "blockchainname.db"),
                                        check_same_thread=False)

        def create_tables(transaction):
            transaction.execute("create table if not exists name_metadata (" +
                                "    name text, " +
                                "    txid text, " +
                                "    n integer, " +
                                "    sd_hash text)")
            transaction.execute("create table if not exists claim_ids (" +
                                "    claimId text, " +
                                "    name text, " +
                                "    txid text, " +
                                "    n integer)")

        return self.db.runInteraction(create_tables)

    def clean_bad_records(self):
        d = self.db.runQuery("delete from name_metadata where length(txid) > 64 or txid is null")
        return d

    def save_name_metadata(self, name, claim_outpoint, sd_hash):
        d = self.db.runQuery(
            "delete from name_metadata where name=? and txid=? and n=? and sd_hash=?",
            (name, claim_outpoint['txid'], claim_outpoint['nout'], sd_hash))
        d.addCallback(
            lambda _: self.db.runQuery(
                "delete from name_metadata where name=? and txid=? and n=? and sd_hash=?",
                (name, claim_outpoint['txid'], UNSET_NOUT, sd_hash)))
        d.addCallback(
            lambda _: self.db.runQuery(
                "insert into name_metadata values (?, ?, ?, ?)",
                (name, claim_outpoint['txid'], claim_outpoint['nout'], sd_hash)))
        return d

    @rerun_if_locked
    def get_claim_metadata_for_sd_hash(self, sd_hash):
        d = self.db.runQuery("select name, txid, n from name_metadata where sd_hash=?", (sd_hash,))
        d.addCallback(lambda r: r[0] if r else None)
        return d

    def update_claimid(self, claim_id, name, claim_outpoint):
        d = self.db.runQuery(
            "delete from claim_ids where claimId=? and name=? and txid=? and n=?",
            (claim_id, name, claim_outpoint['txid'], claim_outpoint['nout']))
        d.addCallback(
            lambda _: self.db.runQuery(
                "delete from claim_ids where claimId=? and name=? and txid=? and n=?",
                (claim_id, name, claim_outpoint['txid'], UNSET_NOUT)))
        d.addCallback(
            lambda r: self.db.runQuery(
                "insert into claim_ids values (?, ?, ?, ?)",
                (claim_id, name, claim_outpoint['txid'], claim_outpoint['nout'])))
        d.addCallback(lambda _: claim_id)
        return d

    def get_claimid_for_tx(self, name, claim_outpoint):
        d = self.db.runQuery(
            "select claimId from claim_ids where name=? and txid=? and n=?",
            (name, claim_outpoint['txid'], claim_outpoint['nout']))
        d.addCallback(lambda r: r[0][0] if r else None)
        return d


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
        def start_manage():
            self.stopped = False
            self.manage()
            return True

        d = self._storage.load()
        d.addCallback(lambda _: self._clean_bad_records())
        d.addCallback(lambda _: self._start())
        d.addCallback(lambda _: start_manage())
        return d

    def _clean_bad_records(self):
        self._storage.clean_bad_records()

    def _save_name_metadata(self, name, claim_outpoint, sd_hash):
        return self._storage.save_name_metadata(name, claim_outpoint, sd_hash)

    def _get_claim_metadata_for_sd_hash(self, sd_hash):
        return self._storage.get_claim_metadata_for_sd_hash(sd_hash)

    def _update_claimid(self, claim_id, name, claim_outpoint):
        return self._storage.update_claimid(claim_id, name, claim_outpoint)

    def _get_claimid_for_tx(self, name, claim_outpoint):
        return self._storage.get_claimid_for_tx(name, claim_outpoint)

    @staticmethod
    def log_stop_error(err):
        log.error("An error occurred stopping the wallet: %s", err.getTraceback())

    def stop(self):
        log.info("Stopping %s", self)
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
    def get_claim(self, claim_id):
        claim = yield self._get_claim_by_claimid(claim_id)
        if not claim:
            log.warning("Claim does not exist: %s", claim_id)
            defer.returnValue(None)
        try:
            decoded = smart_decode(claim['value'])
            claim['value'] = decoded.claim_dict
            claim['hex'] = decoded.serialized.encode('hex')
        except DecodeError:
            claim['hex'] = claim['value']
            claim['value'] = None
            claim['error'] = "Failed to decode"
            log.warning("Failed to decode claim value for lbry://%s#%s", claim['name'],
                        claim['claim_id'])
        defer.returnValue(claim)

    def get_claimid(self, name, txid, nout):
        def _get_id_for_return(claim_id):
            if claim_id:
                return defer.succeed(claim_id)
            else:
                d = self.get_claims_from_tx(txid)
                d.addCallback(
                    lambda claims: next(
                        c for c in claims if c['name'] == name and
                        c['nout'] == claim_outpoint['nout']))
                d.addCallback(
                    lambda claim: self._update_claimid(
                        claim['claim_id'], name, ClaimOutpoint(txid, claim['nout'])))
                return d

        claim_outpoint = ClaimOutpoint(txid, nout)
        d = self._get_claimid_for_tx(name, claim_outpoint)
        d.addCallback(_get_id_for_return)
        return d

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
    def get_claim_info(self, name, txid=None, nout=None, claim_id=None):
        if claim_id is not None:
            results = yield self.get_claim(claim_id)
            if results['name'] != name:
                raise Exception("Name does not match claim referenced by id")
        elif txid is None or nout is None:
            results = yield self.get_claim_by_name(name)
        else:
            results = yield self.get_claim_by_outpoint(ClaimOutpoint(txid, nout))
        defer.returnValue(results)

    @defer.inlineCallbacks
    def _handle_claim_result(self, results):
        if not results:
            raise UnknownNameError("No results to return")

        if 'error' in results:
            if results['error'] == 'name is not claimed':
                raise UnknownNameError(results['error'])
            else:
                raise Exception(results['error'])

        if 'claim' in results:
            claim = results['claim']
            if 'has_signature' in claim and claim['has_signature']:
                if not claim['signature_is_valid']:
                    log.warning("lbry://%s#%s has an invalid signature",
                                claim['name'], claim['claim_id'])
                    decoded = ClaimDict.load_dict(claim['value'])
                    claim_dict = decoded.claim_dict
                    claim['value'] = claim_dict
                    defer.returnValue(claim)
            try:
                decoded = smart_decode(claim['value'])
                claim_dict = decoded.claim_dict
                outpoint = ClaimOutpoint(claim['txid'], claim['nout'])
                name = claim['name']
                claim['value'] = claim_dict
                claim['hex'] = decoded.serialized.encode('hex')
                yield self._save_name_metadata(name, outpoint, decoded.source_hash)
                yield self._update_claimid(claim['claim_id'], name, outpoint)
            except DecodeError:
                claim['hex'] = claim['value']
                claim['value'] = None
                claim['error'] = "Failed to decode value"

            results = claim

        elif 'value' in results:
            if 'has_signature' in results and results['has_signature']:
                if not results['signature_is_valid']:
                    log.warning("lbry://%s#%s has an invalid signature",
                                results['name'], results['claim_id'])
                    decoded = ClaimDict.load_dict(results['value'])
                    claim_dict = decoded.claim_dict
                    results['value'] = claim_dict
                    defer.returnValue(results)
            try:
                decoded = ClaimDict.load_dict(results['value'])
                claim_dict = decoded.claim_dict
                claim_hex = decoded.serialized.encode('hex')
                claim_err = None
                outpoint = ClaimOutpoint(results['txid'], results['nout'])
                name = results['name']
                yield self._save_name_metadata(name, outpoint, decoded.source_hash)
                yield self._update_claimid(results['claim_id'], name, outpoint)
            except DecodeError:
                claim_dict = None
                claim_hex = results['value']
                claim_err = "Failed to decode value"
            if claim_err:
                results['error'] = claim_err
            results['hex'] = claim_hex
            results['value'] = claim_dict

        log.info("get claim info lbry://%s#%s", results['name'], results['claim_id'])
        defer.returnValue(results)

    @defer.inlineCallbacks
    def resolve_uri(self, uri):
        resolve_results = yield self._get_value_for_uri(uri)
        if 'claim' in resolve_results:
            formatted = yield self._handle_claim_result(resolve_results)
            resolve_results['claim'] = formatted
            result = resolve_results
        elif 'claims_in_channel' in resolve_results:
            claims_for_return = []
            for claim in resolve_results['claims_in_channel']:
                formatted = yield self._handle_claim_result(claim)
                claims_for_return.append(formatted)
            resolve_results['claims_in_channel'] = claims_for_return
            result = resolve_results
        elif 'error' in resolve_results:
            raise Exception(resolve_results['error'])
        else:
            result = None
        defer.returnValue(result)

    @defer.inlineCallbacks
    def get_claim_by_outpoint(self, claim_outpoint):
        claim = yield self._get_claim_by_outpoint(claim_outpoint['txid'], claim_outpoint['nout'])
        result = yield self._handle_claim_result(claim)
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
    def claim_name(self, name, bid, metadata, certificate_id=None):
        """
        Claim a name, or update if name already claimed by user

        @param name: str, name to claim
        @param bid: float, bid amount
        @param metadata: ClaimDict compliant dict
        @param certificate_id: str (optional), claim id of channel certificate

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

        claim = yield self._send_name_claim(name, serialized.encode('hex'), bid, certificate_id)

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

    def _send_name_claim(self, name, val, amount, certificate_id=None):
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

    def _start(self):
        pass

    def _stop(self):
        pass


class LBRYumWallet(Wallet):
    def __init__(self, storage, config=None):
        Wallet.__init__(self, storage)
        self._config = config
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
        self.config = make_config(self._config)

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

        storage = lbryum.wallet.WalletStorage(self.config.get_wallet_path())
        if storage.get('use_encryption') is True:
            d.addCallback(lambda _: self.wallet.wait_until_authenticated(self.decrypt_wallet()))
            d.addCallback(lambda _: log.info("Decrypted wallet"))
        return d

    def decrypt_wallet(self):
        import os
        from lbryum.util import InvalidPassword
        import getpass

        password = getpass.getpass("Password for encrypted wallet: ")

        try:
            seed = self.wallet.check_password(password)
            self.wallet.set_is_decrypted(True)
        except InvalidPassword:
            log.error("Error: This password does not decode this wallet.")
            os._exit(1)


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

        if self.network:
            self.network.stop()

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
    def _send_name_claim(self, name, value, amount, certificate_id=None):
        log.info("Send claim: %s for %s: %s ", name, amount, value)
        claim_out = yield self._run_cmd_as_defer_succeed('claim', name, value, amount,
                                                         certificate_id=certificate_id)
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
        txid = yield self._run_cmd_as_defer_to_thread('broadcast', raw_tx)
        log.info("Broadcast tx: %s", txid)
        if len(txid) != 64:
            raise Exception("Transaction rejected. Raw tx: {}".format(raw_tx))
        defer.returnValue(txid)

    def _do_send_many(self, payments_to_send):
        def broadcast_send_many(paytomany_out):
            if 'hex' not in paytomany_out:
                raise Exception('Unepxected paytomany output:{}'.format(paytomany_out))
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

    def _claim_certificate(self, name, amount):
        return self._run_cmd_as_defer_to_thread('claimcertificate', name, amount)

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