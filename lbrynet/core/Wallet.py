# pylint: disable=line-too-long
# TODO: renable pylint check after lbrycrdd code is removed
import datetime
import logging
import json
import os

from twisted.internet import threads, reactor, defer, task
from twisted.python.failure import Failure
from twisted.enterprise import adbapi
from collections import defaultdict, deque
from zope.interface import implements
from jsonschema import ValidationError
from decimal import Decimal

from lbryum import SimpleConfig, Network
from lbryum.lbrycrd import COIN
import lbryum.wallet
from lbryum.commands import known_commands, Commands
from lbryum.transaction import Transaction

from lbrynet.interfaces import IRequestCreator, IQueryHandlerFactory, IQueryHandler, IWallet
from lbrynet.core.client.ClientRequest import ClientRequest
from lbrynet.core.Error import UnknownNameError, InvalidStreamInfoError, RequestCanceledError
from lbrynet.db_migrator.migrate1to2 import UNSET_NOUT
from lbrynet.metadata.Metadata import Metadata

log = logging.getLogger(__name__)
alert = logging.getLogger("lbryalert." + __name__)


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
        else:
            raise TypeError('cannot compare {}'.format(type(compare)))
    def __ne__(self, compare):
        return not self.__eq__(compare)




class Wallet(object):
    """This class implements the Wallet interface for the LBRYcrd payment system"""
    implements(IWallet)

    _FIRST_RUN_UNKNOWN = 0
    _FIRST_RUN_YES = 1
    _FIRST_RUN_NO = 2

    def __init__(self, db_dir):
        self.db_dir = db_dir
        self.db = None
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

        self.is_lagging = None

        self.manage_running = False
        self._manage_count = 0
        self._balance_refresh_time = 3
        self._batch_count = 20
        self._first_run = self._FIRST_RUN_UNKNOWN

    def start(self):

        def start_manage():
            self.stopped = False
            self.manage()
            return True

        d = self._open_db()
        d.addCallback(lambda _: self._clean_bad_records())
        d.addCallback(lambda _: self._start())
        d.addCallback(lambda _: start_manage())
        return d

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

            d.addCallback(lambda _: self.get_balance())

            def set_wallet_balance(balance):
                if self.wallet_balance != balance:
                    log.debug("Got a new balance: %s", str(balance))
                self.wallet_balance = balance

            def log_error(err):
                if isinstance(err, AttributeError):
                    log.warning("Failed to get an updated balance")
                    log.warning("Last balance update: %s", str(self.wallet_balance))

            d.addCallbacks(set_wallet_balance, log_error)
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
        #if peer in self.peer_addresses:
        if self.wallet_balance >= self.total_reserved_points + rounded_amount:
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
        assert(rounded_amount <= reserved_points.amount)
        assert(peer in self.peer_addresses)
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
        assert(rounded_amount <= reserved_points.amount)
        self.queued_payments[address] += rounded_amount
        self.total_reserved_points -= (reserved_points.amount - rounded_amount)
        log.debug("Ordering that %s points be sent to %s", str(rounded_amount),
                 str(address))
        return defer.succeed(True)

    def add_expected_payment(self, peer, amount):
        """Increase the number of points expected to be paid by a peer"""
        rounded_amount = Decimal(str(round(amount, 8)))
        assert(peer in self.current_address_given_to_peer)
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

    def get_new_address_for_peer(self, peer):
        def set_address_for_peer(address):
            self.current_address_given_to_peer[peer] = address
            return address
        d = self.get_new_address()
        d.addCallback(set_address_for_peer)
        return d

    def _send_payments(self):
        payments_to_send = {}
        for address, points in self.queued_payments.items():
            if points > 0:
                log.debug("Should be sending %s points to %s", str(points), str(address))
                payments_to_send[address] = points
                self.total_reserved_points -= points
                self.wallet_balance -= points
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

    def get_stream_info_for_name(self, name):
        d = self._get_value_for_name(name)
        d.addCallback(self._get_stream_info_from_value, name)
        return d

    def get_txid_for_name(self, name):
        d = self._get_value_for_name(name)
        d.addCallback(lambda r: None if 'txid' not in r else r['txid'])
        return d

    def get_stream_info_from_claim_outpoint(self, name, txid, nout):
        claim_outpoint = ClaimOutpoint(txid, nout)
        d = self.get_claims_from_tx(claim_outpoint['txid'])

        def get_claim_for_name(claims):
            for claim in claims:
                if claim_outpoint == claim:
                    claim['txid'] = txid
                    return claim
            return Failure(UnknownNameError(name))

        d.addCallback(get_claim_for_name)
        d.addCallback(self._get_stream_info_from_value, name)
        return d

    def _get_stream_info_from_value(self, result, name):
        def _check_result_fields(r):
            for k in ['value', 'txid', 'n', 'height', 'amount']:
                assert k in r, "getvalueforname response missing field %s" % k

        def _log_success(claim_id):
            log.debug("lbry://%s complies with %s, claimid: %s", name, metadata.version, claim_id)
            return defer.succeed(None)
        if 'error' in result:
            log.warning("Got an error looking up a name: %s", result['error'])
            return Failure(UnknownNameError(name))
        _check_result_fields(result)
        try:
            metadata = Metadata(json.loads(result['value']))
        except (TypeError, ValueError, ValidationError):
            return Failure(InvalidStreamInfoError(name, result['value']))
        sd_hash = metadata['sources']['lbry_sd_hash']
        claim_outpoint = ClaimOutpoint(result['txid'], result['n'])
        d = self._save_name_metadata(name, claim_outpoint, sd_hash)
        d.addCallback(lambda _: self.get_claimid(name, result['txid'], result['n']))
        d.addCallback(lambda cid: _log_success(cid))
        d.addCallback(lambda _: metadata)
        return d

    def get_claim(self, name, claim_id):
        d = self.get_claims_for_name(name)
        d.addCallback(lambda claims: next(claim for claim in claims['claims'] if claim['claimId'] == claim_id))
        return d

    def get_claimid(self, name, txid, nout):
        def _get_id_for_return(claim_id):
            if claim_id:
                return defer.succeed(claim_id)
            else:
                d = self.get_claims_from_tx(txid)
                d.addCallback(lambda claims: next(c for c in claims if c['name'] == name and c['nOut'] == claim_outpoint['nout']))
                d.addCallback(lambda claim: self._update_claimid(claim['claimId'], name, ClaimOutpoint(txid, claim['nOut'])))
                return d
        claim_outpoint = ClaimOutpoint(txid, nout)
        d = self._get_claimid_for_tx(name, claim_outpoint)
        d.addCallback(_get_id_for_return)
        return d

    def get_my_claim(self, name):
        def _get_claim_for_return(claim):
            if not claim:
                return False
            claim['value'] = json.loads(claim['value'])
            return claim


        def _get_my_unspent_claim(claims):
            for claim in claims:
                if claim['name'] == name and not claim['is spent'] and claim['category'] != 'support':
                    return claim
            return False

        d = self.get_name_claims()
        d.addCallback(_get_my_unspent_claim)
        d.addCallback(_get_claim_for_return)
        return d

    def get_claim_info(self, name, txid=None, nout=None):
        if txid is None or nout is None:
            d = self._get_value_for_name(name)
            d.addCallback(lambda r: self._get_claim_info(name, ClaimOutpoint(r['txid'], r['n'])))
        else:
            d = self._get_claim_info(name, ClaimOutpoint(txid, nout))
        d.addErrback(lambda _: False)
        return d

    def _format_claim_for_return(self, name, claim, metadata=None, meta_version=None):
        result = {}
        result['claim_id'] = claim['claimId']
        result['amount'] = claim['nEffectiveAmount']
        result['height'] = claim['nHeight']
        result['name'] = name
        result['txid'] = claim['txid']
        result['nout'] = claim['n']
        result['value'] = metadata if metadata else json.loads(claim['value'])
        result['supports'] = [{'txid': support['txid'], 'n': support['n']} for support in claim['supports']]
        result['meta_version'] = meta_version if meta_version else result['value'].get('ver', '0.0.1')
        return result

    def _get_claim_info(self, name, claim_outpoint):
        def _build_response(claim):
            try:
                metadata = Metadata(json.loads(claim['value']))
                meta_ver = metadata.version
                sd_hash = metadata['sources']['lbry_sd_hash']
                d = self._save_name_metadata(name, claim_outpoint, sd_hash)
            except (TypeError, ValueError, ValidationError):
                metadata = claim['value']
                meta_ver = "Non-compliant"
                d = defer.succeed(None)

            d.addCallback(lambda _: self._format_claim_for_return(name,
                                                                  claim,
                                                                  metadata=metadata,
                                                                  meta_version=meta_ver))
            log.debug("get claim info lbry://%s metadata: %s, claimid: %s", name, meta_ver, claim['claimId'])

            return d

        d = self.get_claimid(name, claim_outpoint['txid'], claim_outpoint['nout'])
        d.addCallback(lambda claim_id: self.get_claim(name, claim_id))
        d.addCallback(_build_response)
        return d

    def get_claims_for_name(self, name):
        d = self._get_claims_for_name(name)
        return d

    def update_metadata(self, new_metadata, old_metadata):
        meta_for_return = old_metadata if isinstance(old_metadata, dict) else {}
        for k in new_metadata:
            meta_for_return[k] = new_metadata[k]
        return defer.succeed(Metadata(meta_for_return))


    def claim_name(self, name, bid, m):
        def _save_metadata(claim_out, metadata):
            if not claim_out['success']:
                msg = 'Claim to name {} failed: {}'.format(name, claim_out['reason'])
                raise Exception(msg)
            claim_out.pop('success')
            claim_outpoint = ClaimOutpoint(claim_out['txid'], claim_out['nout'])
            log.debug("Saving metadata for claim %s %d" % (claim_outpoint['txid'], claim_outpoint['nout']))
            d = self._save_name_metadata(name, claim_outpoint, metadata['sources']['lbry_sd_hash'])
            d.addCallback(lambda _: claim_out)
            return d

        def _claim_or_update(claim, metadata, _bid):
            if not claim:
                log.debug("No own claim yet, making a new one")
                return self._send_name_claim(name, metadata, _bid)
            else:
                log.debug("Updating over own claim")
                d = self.update_metadata(metadata, claim['value'])
                claim_outpoint = ClaimOutpoint(claim['txid'], claim['nOut'])
                d.addCallback(lambda new_metadata: self._send_name_claim_update(name, claim['claim_id'],
                                                                                claim_outpoint,
                                                                                new_metadata, _bid))
                return d

        meta = Metadata(m)
        d = self.get_my_claim(name)
        d.addCallback(lambda claim: _claim_or_update(claim, meta, bid))
        d.addCallback(lambda claim_out: _save_metadata(claim_out, meta))
        return d

    def abandon_claim(self, txid, nout):
        def _parse_abandon_claim_out(claim_out):
            if not claim_out['success']:
                msg = 'Abandon of {}:{} failed: {}'.format(txid, nout, claim_out['resason'])
                raise Exception(msg)
            claim_out.pop('success')
            return defer.succeed(claim_out)

        claim_outpoint = ClaimOutpoint(txid, nout)
        d = self._abandon_claim(claim_outpoint)
        d.addCallback(lambda claim_out: _parse_abandon_claim_out(claim_out))
        return d

    def support_claim(self, name, claim_id, amount):
        def _parse_support_claim_out(claim_out):
            if not claim_out['success']:
                msg = 'Support of {}:{} failed: {}'.format(name, claim_id, claim_out['reason'])
                raise Exception(msg)
            claim_out.pop('success')
            return defer.succeed(claim_out)

        d = self._support_claim(name, claim_id, amount)
        d.addCallback(lambda claim_out: _parse_support_claim_out(claim_out))
        return d

    def get_tx(self, txid):
        d = self._get_raw_tx(txid)
        d.addCallback(self._get_decoded_tx)
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

    def get_name_and_validity_for_sd_hash(self, sd_hash):
        def _get_status_of_claim(name_txid, sd_hash):
            if name_txid:
                claim_outpoint = ClaimOutpoint(name_txid[1], name_txid[2])
                name = name_txid[0]
                return self._get_status_of_claim(claim_outpoint, name, sd_hash)
            else:
                return None

        d = self._get_claim_metadata_for_sd_hash(sd_hash)
        d.addCallback(lambda name_txid: _get_status_of_claim(name_txid, sd_hash))
        return d

    def get_available_balance(self):
        return float(self.wallet_balance - self.total_reserved_points)

    def is_first_run(self):
        if self._first_run == self._FIRST_RUN_UNKNOWN:
            d = self._check_first_run()

            def set_first_run(is_first):
                self._first_run = self._FIRST_RUN_YES if is_first else self._FIRST_RUN_NO

            d.addCallback(set_first_run)
        else:
            d = defer.succeed(self._FIRST_RUN_YES if self._first_run else self._FIRST_RUN_NO)

        d.addCallback(lambda _: self._first_run == self._FIRST_RUN_YES)
        return d

    def _get_status_of_claim(self, claim_outpoint, name, sd_hash):
        d = self.get_claims_from_tx(claim_outpoint['txid'])

        def get_status(claims):
            if claims is None:
                claims = []
            for claim in claims:
                if 'in claim trie' in claim:
                    name_is_equal = 'name' in claim and str(claim['name']) == name
                    nout_is_equal = 'nOut' in claim and claim['nOut'] == claim_outpoint['nout']
                    if name_is_equal and nout_is_equal and 'value' in claim:
                        try:
                            value_dict = json.loads(claim['value'])
                        except (ValueError, TypeError):
                            return None
                        claim_sd_hash = None
                        if 'stream_hash' in value_dict:
                            claim_sd_hash = str(value_dict['stream_hash'])
                        if 'sources' in value_dict and 'lbrynet_sd_hash' in value_dict['sources']:
                            claim_sd_hash = str(value_dict['sources']['lbry_sd_hash'])
                        if claim_sd_hash is not None and claim_sd_hash == sd_hash:
                            if 'is controlling' in claim and claim['is controlling']:
                                return name, "valid"
                            if claim['in claim trie']:
                                return name, "invalid"
                            if 'in queue' in claim and claim['in queue']:
                                return name, "pending"
                            return name, "unconfirmed"
            return None

        d.addCallback(get_status)
        return d

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
                            new_expected_balance = (balance[0],
                                                    balance[1],
                                                    balance[2],
                                                    datetime.datetime.now() + self.max_expected_payment_time,
                                                    balance[4] + 1,
                                                    balance[5])
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

    def _open_db(self):
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

    def _clean_bad_records(self):
        d = self.db.runQuery("delete from name_metadata where length(txid) > 64 or txid is null")
        return d


    def _save_name_metadata(self, name, claim_outpoint, sd_hash):
        d = self.db.runQuery("delete from name_metadata where name=? and txid=? and n=? and sd_hash=?",
                             (name, claim_outpoint['txid'], claim_outpoint['nout'], sd_hash))
        d.addCallback(
            lambda _: self.db.runQuery("delete from name_metadata where name=? and txid=? and n=? and sd_hash=?",
                (name, claim_outpoint['txid'], UNSET_NOUT, sd_hash)))

        d.addCallback(lambda _: self.db.runQuery("insert into name_metadata values (?, ?, ?, ?)",
                                                 (name, claim_outpoint['txid'], claim_outpoint['nout'], sd_hash)))
        return d

    def _get_claim_metadata_for_sd_hash(self, sd_hash):
        d = self.db.runQuery("select name, txid, n from name_metadata where sd_hash=?", (sd_hash,))
        d.addCallback(lambda r: r[0] if r else None)
        return d

    def _update_claimid(self, claim_id, name, claim_outpoint):
        d = self.db.runQuery("delete from claim_ids where claimId=? and name=? and txid=? and n=?",
                             (claim_id, name, claim_outpoint['txid'], claim_outpoint['nout']))
        d.addCallback(
            lambda _: self.db.runQuery("delete from claim_ids where claimId=? and name=? and txid=? and n=?",
                             (claim_id, name, claim_outpoint['txid'], UNSET_NOUT)))

        d.addCallback(lambda r: self.db.runQuery("insert into claim_ids values (?, ?, ?, ?)",
                                                 (claim_id, name, claim_outpoint['txid'], claim_outpoint['nout'])))
        d.addCallback(lambda _: claim_id)
        return d

    def _get_claimid_for_tx(self, name, claim_outpoint):
        d = self.db.runQuery("select claimId from claim_ids where name=? and txid=? and n=?", (name, claim_outpoint['txid'], claim_outpoint['nout']))
        d.addCallback(lambda r: r[0][0] if r else None)
        return d

    ######### Must be overridden #########

    def get_balance(self):
        return defer.fail(NotImplementedError())

    def get_new_address(self):
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

    def _check_first_run(self):
        return defer.fail(NotImplementedError())

    def _get_raw_tx(self, txid):
        return defer.fail(NotImplementedError())

    def _send_name_claim(self, name, val, amount):
        return defer.fail(NotImplementedError())

    def _get_decoded_tx(self, raw_tx):
        return defer.fail(NotImplementedError())

    def _abandon_claim(self, claim_outpoint):
        return defer.fail(NotImplementedError())

    def _send_name_claim_update(self, name, claim_id, claim_outpoint, value, amount):
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

    def _get_transaction(self, txid):
        return defer.fail(NotImplementedError())

    def _start(self):
        pass

    def _stop(self):
        pass


class LBRYumWallet(Wallet):

    def __init__(self, db_dir, config=None):
        Wallet.__init__(self, db_dir)
        self._config = config
        self.network = None
        self.wallet = None
        self.cmd_runner = None
        self.first_run = False
        self.printed_retrieving_headers = False
        self._start_check = None
        self._catch_up_check = None
        self._caught_up_counter = 0
        self._lag_counter = 0
        self.blocks_behind_alert = 0
        self.catchup_progress = 0
        self.max_behind = 0

    def _start(self):

        network_start_d = defer.Deferred()

        def setup_network():
            self.config = make_config(self._config)
            self.network = Network(self.config)
            alert.info("Loading the wallet...")
            return defer.succeed(self.network.start())

        d = setup_network()

        def check_started():
            if self.network.is_connecting():
                if not self.printed_retrieving_headers and self.network.blockchain.retrieving_headers:
                    alert.info("Running the wallet for the first time...this may take a moment.")
                    self.printed_retrieving_headers = True
                return False
            self._start_check.stop()
            self._start_check = None
            if self.network.is_connected():
                network_start_d.callback(True)
            else:
                network_start_d.errback(ValueError("Failed to connect to network."))

        self._start_check = task.LoopingCall(check_started)

        d.addCallback(lambda _: self._start_check.start(.1))
        d.addCallback(lambda _: network_start_d)
        d.addCallback(lambda _: self._load_wallet())
        d.addCallback(lambda _: self._get_cmd_runner())
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

        if self.network:
            self.network.stop()

        stop_check = task.LoopingCall(check_stopped)
        stop_check.start(.1)
        return d

    def _load_wallet(self):

        def get_wallet():
            path = self.config.get_wallet_path()
            storage = lbryum.wallet.WalletStorage(path)
            wallet = lbryum.wallet.Wallet(storage)
            if not storage.file_exists:
                self.first_run = True
                seed = wallet.make_seed()
                wallet.add_seed(seed, None)
                wallet.create_master_keys(None)
                wallet.create_main_account()
                wallet.synchronize()
            self.wallet = wallet

        blockchain_caught_d = defer.Deferred()

        def check_caught_up():
            local_height = self.network.get_catchup_progress()
            remote_height = self.network.get_server_height()

            if remote_height != 0 and remote_height - local_height <= 5:
                msg = ""
                if self._caught_up_counter != 0:
                    msg += "All caught up. "
                msg += "Wallet loaded."
                alert.info(msg)
                self._catch_up_check.stop()
                self._catch_up_check = None
                blockchain_caught_d.callback(True)

            elif remote_height != 0:
                past_blocks_behind = self.blocks_behind_alert
                self.blocks_behind_alert = remote_height - local_height
                if self.blocks_behind_alert < past_blocks_behind:
                    self._lag_counter = 0
                    self.is_lagging = False
                else:
                    self._lag_counter += 1
                    if self._lag_counter >= 900:
                        self.is_lagging = True

                if self.blocks_behind_alert > self.max_behind:
                    self.max_behind = self.blocks_behind_alert
                self.catchup_progress = int(100 * (self.blocks_behind_alert / (5 + self.max_behind)))
                if self._caught_up_counter == 0:
                    alert.info('Catching up with the blockchain...showing blocks left...')
                if self._caught_up_counter % 30 == 0:
                    alert.info('%d...', (remote_height - local_height))

                self._caught_up_counter += 1

        def log_error(err):
            log.warning(err.getErrorMessage())
            return defer.fail(err)

        self._catch_up_check = task.LoopingCall(check_caught_up)

        d = threads.deferToThread(get_wallet)
        d.addCallback(self._save_wallet)
        d.addCallback(lambda _: self.wallet.start_threads(self.network))
        d.addCallback(lambda _: self._catch_up_check.start(.1))
        d.addErrback(log_error)
        d.addCallback(lambda _: blockchain_caught_d)
        return d

    def _get_cmd_runner(self):
        self.cmd_runner = Commands(self.config, self.wallet, self.network)

    def get_balance(self):
        cmd = known_commands['getbalance']
        func = getattr(self.cmd_runner, cmd.name)
        accounts = None
        exclude_claimtrietx = True
        d = threads.deferToThread(func, accounts, exclude_claimtrietx)
        d.addCallback(lambda result: Decimal(result['confirmed']) + Decimal(result.get('unconfirmed', 0.0)))
        return d

    def get_new_address(self):
        d = threads.deferToThread(self.wallet.create_new_address)
        d.addCallback(self._save_wallet)
        return d

    def get_block(self, blockhash):
        cmd = known_commands['getblock']
        func = getattr(self.cmd_runner, cmd.name)
        return threads.deferToThread(func, blockhash)

    def get_most_recent_blocktime(self):
        header = self.network.get_header(self.network.get_local_height())
        return defer.succeed(header['timestamp'])

    def get_best_blockhash(self):
        height = self.network.get_local_height()
        d = threads.deferToThread(self.network.blockchain.read_header, height)
        d.addCallback(lambda header: self.network.blockchain.hash_header(header))
        return d

    def _get_blockhash(self, height):
        d = threads.deferToThread(self.network.blockchain.read_header, height)
        d.addCallback(lambda header: self.network.blockchain.hash_header(header))
        return d

    def get_name_claims(self):
        cmd = known_commands['getnameclaims']
        func = getattr(self.cmd_runner, cmd.name)
        return threads.deferToThread(func)

    def _check_first_run(self):
        return defer.succeed(self.first_run)

    def _get_raw_tx(self, txid):
        cmd = known_commands['gettransaction']
        func = getattr(self.cmd_runner, cmd.name)
        return threads.deferToThread(func, txid)

    def _get_transaction(self, txid):
        def _add_confirms(tx):
            tx['confirmations'] = self.wallet.get_confirmations(txid)
            return tx

        d = self._get_raw_tx(txid)
        d.addCallback(self._get_decoded_tx)
        d.addCallback(_add_confirms)
        return d

    def _send_name_claim(self, name, val, amount):
        cmd = known_commands['claim']
        func = getattr(self.cmd_runner, cmd.name)
        return threads.deferToThread(func, name, json.dumps(val), amount)

    def _get_claims_for_name(self, name):
        cmd = known_commands['getclaimsforname']
        func = getattr(self.cmd_runner, cmd.name)
        return threads.deferToThread(func, name)

    def _send_name_claim_update(self, name, claim_id, claim_outpoint, value, amount):
        metadata = json.dumps(value)
        log.debug("Update %s %d %f %s %s '%s'", claim_outpoint['txid'], claim_outpoint['nout'],
                                                     amount, name, claim_id, metadata)
        cmd = known_commands['update']
        func = getattr(self.cmd_runner, cmd.name)
        return threads.deferToThread(func, claim_outpoint['txid'], claim_outpoint['nout'], name, claim_id, metadata, amount)


    def _get_decoded_tx(self, raw_tx):
        tx = Transaction(raw_tx)
        decoded_tx = {}
        decoded_tx['vout'] = []
        for output in tx.outputs():
            out = {}
            out['value'] = Decimal(output[2]) / Decimal(COIN)
            decoded_tx['vout'].append(out)
        return decoded_tx

    def _abandon_claim(self, claim_outpoint):
        log.debug("Abandon %s %s" % (claim_outpoint['txid'], claim_outpoint['nout']))
        cmd = known_commands['abandon']
        func = getattr(self.cmd_runner, cmd.name)
        d = threads.deferToThread(func, claim_outpoint['txid'], claim_outpoint['nout'])
        return d

    def _support_claim(self, name, claim_id, amount):
        log.debug("Support %s %s %f" % (name, claim_id, amount))
        cmd = known_commands['support']
        func = getattr(self.cmd_runner, cmd.name)
        d = threads.deferToThread(func, name, claim_id, amount)
        return d

    def _broadcast_transaction(self, raw_tx):
        def _log_tx(r):
            log.debug("Broadcast tx: %s", r)
            return r
        cmd = known_commands['broadcast']
        func = getattr(self.cmd_runner, cmd.name)
        d = threads.deferToThread(func, raw_tx)
        d.addCallback(_log_tx)
        d.addCallback(
            lambda r: r if len(r) == 64 else defer.fail(Exception("Transaction rejected")))
        d.addCallback(self._save_wallet)
        return d

    def _do_send_many(self, payments_to_send):
        log.warning("Doing send many. payments to send: %s", str(payments_to_send))
        cmd = known_commands['paytomanyandsend']
        func = getattr(self.cmd_runner, cmd.name)
        return threads.deferToThread(func, payments_to_send.iteritems())

    def _get_value_for_name(self, name):
        cmd = known_commands['getvalueforname']
        func = getattr(self.cmd_runner, cmd.name)
        return threads.deferToThread(func, name)

    def get_claims_from_tx(self, txid):
        cmd = known_commands['getclaimsfromtx']
        func = getattr(self.cmd_runner, cmd.name)
        return threads.deferToThread(func, txid)

    def _get_balance_for_address(self, address):
        return defer.succeed(Decimal(self.wallet.get_addr_received(address))/COIN)

    def get_nametrie(self):
        cmd = known_commands['getclaimtrie']
        func = getattr(self.cmd_runner, cmd.name)
        return threads.deferToThread(func)

    def _get_history(self):
        cmd = known_commands['history']
        func = getattr(self.cmd_runner, cmd.name)
        return threads.deferToThread(func)

    def _address_is_mine(self, address):
        cmd = known_commands['ismine']
        func = getattr(self.cmd_runner, cmd.name)
        return threads.deferToThread(func, address)

    def get_pub_keys(self, wallet):
        cmd = known_commands['getpubkeys']
        func = getattr(self.cmd_runner, cmd.name)
        return threads.deferToThread(func, wallet)

    def _save_wallet(self, val):
        d = threads.deferToThread(self.wallet.storage.write)
        d.addCallback(lambda _: val)
        return d


class LBRYcrdAddressRequester(object):
    implements([IRequestCreator])

    def __init__(self, wallet):
        self.wallet = wallet
        self._protocols = []

    ######### IRequestCreator #########

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

    ######### internal calls #########

    def _handle_address_response(self, response_dict, peer, request, protocol):
        assert request.response_identifier in response_dict, \
            "Expected %s in dict but did not get it" % request.response_identifier
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

    ######### IQueryHandlerFactory #########

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

    ######### IQueryHandler #########

    def register_with_request_handler(self, request_handler, peer):
        self.peer = peer
        request_handler.register_query_handler(self, self.query_identifiers)

    def handle_queries(self, queries):

        def create_response(address):
            self.address = address
            fields = {'lbrycrd_address': address}
            return fields

        if self.query_identifiers[0] in queries:
            d = self.wallet.get_new_address_for_peer(self.peer)
            d.addCallback(create_response)
            return d
        if self.address is None:
            log.warning("Expected a request for an address, but did not receive one")
            return defer.fail(Failure(ValueError("Expected but did not receive an address request")))
        else:
            return defer.succeed({})


def make_config(config=None):
    if config is None:
        config = {}
    return SimpleConfig(config) if type(config) == type({}) else config
