import datetime
import logging
import json

from twisted.internet import threads, reactor, defer, task
from twisted.python.failure import Failure
from collections import defaultdict, deque
from zope.interface import implements
from jsonschema import ValidationError
from decimal import Decimal

from lbryum import SimpleConfig, Network, wallet as lbryum_wallet
from lbryum.lbrycrd import COIN, RECOMMENDED_CLAIMTRIE_HASH_CONFIRMS
from lbryum.commands import known_commands, Commands

from lbrynet import conf
from lbrynet.core import utils
from lbrynet.core.client.ClientRequest import ClientRequest
from lbrynet.core.Error import UnknownNameError, InvalidStreamInfoError, RequestCanceledError
from lbrynet.core.Error import InsufficientFundsError
from lbrynet.interfaces import IRequestCreator, IQueryHandlerFactory, IQueryHandler, IWallet
from lbrynet.metadata.Metadata import Metadata

log = logging.getLogger(__name__)

STATUS_INIT = "INIT"
STATUS_PENDING = "PENDING"
STATUS_ACTIVE = "ACTIVE"
STATUS_INACTIVE = "INACTIVE"
STATUS_INVALID_METADATA = "INVALID_METADATA"

CLAIM_STATUS = [
    STATUS_INIT,
    STATUS_PENDING,
    STATUS_ACTIVE,
    STATUS_INACTIVE,
    STATUS_INVALID_METADATA
]


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
        elif type(compare) in [str, unicode]:
            return compare == self.__repr__()
        else:
            raise TypeError('cannot compare {}'.format(type(compare)))

    def __ne__(self, compare):
        return not self.__eq__(compare)

    @classmethod
    def from_string(cls, outpoint_string):
        txid, nout = outpoint_string.split(":")
        return cls(txid, nout)

    @property
    def as_tuple(self):
        return (self['txid'], self['nout'])


class Wallet(object):
    """This class implements the Wallet interface for the LBRYcrd payment system"""
    implements(IWallet)

    def __init__(self, storage):
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

        self.manage_running = False
        self._manage_count = 0
        self._balance_refresh_time = 3
        self._batch_count = 20

    def start(self):
        def start_manage():
            self.stopped = False
            self.manage()
            return True

        d = self._start()
        d.addCallback(lambda _: start_manage())
        d.addCallback(lambda _: self.initialize_claims())
        return d

    def _clean_bad_records(self):
        self._storage.clean_bad_records()

    def _save_name_metadata(self, name, claim_outpoint, claim_id, metadata, amount, height,
                            is_mine=False, update=False):
        return self._storage.save_name_metadata(name, claim_outpoint, claim_id,
                                                metadata, amount, height, is_mine, update)

    # TODO: use file ids
    def _get_claim_metadata_for_sd_hash(self, sd_hash):
        return self._storage.get_claim_metadata_for_sd_hash(sd_hash)

    def _update_claimid(self, claim_id, claim_outpoint):
        return self._storage.update_claimid(claim_id, claim_outpoint)

    def _get_claimid_for_tx(self, claim_outpoint):
        return self._storage.get_claimid_for_tx(claim_outpoint)

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
    def initialize_claims(self):
        outpoints_missing_sd_info = yield self._storage.claims_missing_sd_info()
        if outpoints_missing_sd_info:
            for outpoint in outpoints_missing_sd_info:
                claim = yield self.get_claim_from_outpoint(outpoint['txid'], outpoint['nout'])
                if claim is not None:
                    yield self._storage.add_metadata_to_claim(outpoint, claim['value'])
                else:
                    log.warning("Unable to get sd info for claim %s", outpoint)
            yield self._storage.repair_claims()

        my_claims = yield self.get_name_claims()
        for claim in my_claims:
            if not claim.get('supported_claimid', False):
                is_spent = claim['is spent']
                confirmations = claim['confirmations']
                name = claim['name']
                try:
                    claim['value'] = json.loads(claim['value'])
                    valid_metadata = True
                except Exception as err:
                    claim['value'] = ""
                    valid_metadata = False
                outpoint = ClaimOutpoint(claim['txid'], claim['nOut'])
                yield self._save_name_metadata(name, outpoint,
                                               claim['claim_id'],
                                               claim['value'],
                                               int(claim['amount'] * COIN),
                                               claim['height'],
                                               is_mine=True,
                                               update=True)
                if is_spent:
                    yield self._storage.update_claim_status(outpoint, STATUS_INACTIVE)
                elif confirmations < RECOMMENDED_CLAIMTRIE_HASH_CONFIRMS:
                    yield self._storage.update_claim_status(outpoint, STATUS_PENDING)
                elif not valid_metadata:
                    yield self._storage.update_claim_status(outpoint, STATUS_INVALID_METADATA)
                else:
                    yield self._storage.update_claim_status(outpoint, STATUS_ACTIVE)
        defer.returnValue(True)

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
            else:
                log.debug("Skipping dust")

            del self.queued_payments[address]

        if payments_to_send:
            log.debug("Creating a transaction with outputs %s", str(payments_to_send))
            d = self._do_send_many(payments_to_send)
            d.addCallback(lambda txid: log.info("Sent transaction %s", txid))
            return d

        log.debug("There were no payments to send")
        return defer.succeed(True)

    def refresh_stream_info_for_name(self, name):
        log.info("Resolving stream info for lbry://%s", name)
        d = self._get_value_for_name(name)
        d.addCallback(self._get_stream_info_from_value, name)
        return d

    @defer.inlineCallbacks
    def get_stream_info_for_name(self, name, force_refresh=True):
        if force_refresh:
            result = yield self.refresh_stream_info_for_name(name)
        else:
            last_checked = yield self._storage.last_checked_winning_name(name)
            if not last_checked or (utils.time() - last_checked) >= conf.settings['cache_time']:
                result = yield self.refresh_stream_info_for_name(name)
            else:
                log.debug("Using cached stream info for lbry://%s", name)
                result = yield self._storage.get_winning_metadata(name)
        defer.returnValue(result)

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

    @defer.inlineCallbacks
    def get_claim_from_outpoint(self, txid, nout):
        claim_out = {}
        claims_in_tx = yield self.get_claims_from_tx(txid)
        result = None
        if claims_in_tx is not None:
            for claim in claims_in_tx:
                if nout == claim['nOut']:
                    claim_out['value'] = json.loads(claim['value'])
                    claim_out['nout'] = claim['nOut']
                    claim_out['txid'] = txid
                    claim_out['name'] = claim['name']
                    claim_out['claim_id'] = claim['claimId']
                    result = claim_out
                    break
        defer.returnValue(result)

    def _get_stream_info_from_value(self, result, name):
        def _check_result_fields(r):
            for k in ['value', 'txid', 'nout', 'height', 'amount']:
                assert k in r, "getvalueforname response missing field %s" % k

        def _log_success(claim_id):
            log.debug("lbry://%s complies with %s, claimid: %s", name, metadata.version, claim_id)

        if 'error' in result:
            log.warning("Got an error looking up lbry://%s: %s", name, result['error'])
            return Failure(UnknownNameError(name))
        _check_result_fields(result)
        try:
            metadata = Metadata(json.loads(result['value']))
        except (TypeError, ValueError, ValidationError):
            return Failure(InvalidStreamInfoError(name, result['value']))

        d = self.get_claimid(name, result['txid'], result['nout'])
        d.addCallback(_log_success)
        d.addCallback(lambda _: metadata)
        return d

    def get_claim(self, name, claim_id):
        d = self.get_claims_for_name(name)
        d.addCallback(
            lambda claims: next(
                claim for claim in claims['claims'] if claim['claim_id'] == claim_id))
        return d

    @defer.inlineCallbacks
    def get_claimid(self, name, txid, nout):
        claim_outpoint = ClaimOutpoint(txid, nout)
        claim_id = yield self._storage.get_claimid_for_tx(claim_outpoint)
        if not claim_id:
            claims = yield self.get_claims_from_tx(txid)
            for claim in claims:
                if claim['name'] == name and claim['nout'] == nout:
                    claim_id = claim['claim_id']
                    yield self._update_claimid(claim_id, claim_outpoint)
                    break
        defer.returnValue(claim_id)

    @defer.inlineCallbacks
    def get_my_claim(self, name):
        my_claims = yield self.get_name_claims()
        my_unspent_claim = False
        for claim in my_claims:
            is_unspent = (
                claim['name'] == name and
                not claim['is_spent'] and
                not claim.get('supported_claimid', False)
            )
            if is_unspent:
                my_unspent_claim = claim
                my_unspent_claim['value'] = json.loads(claim['value'])
                outpoint = ClaimOutpoint(my_unspent_claim['txid'], my_unspent_claim['nout'])
                yield self._save_name_metadata(name, outpoint,
                                               my_unspent_claim['claim_id'],
                                               my_unspent_claim['value'],
                                               my_unspent_claim['amount'],
                                               my_unspent_claim['height'],
                                               is_mine=True,
                                               update=True)
        defer.returnValue(my_unspent_claim)

    @defer.inlineCallbacks
    def get_claim_info(self, name, txid=None, nout=None):
        if txid is None or nout is None:
            last_checked = yield self._storage.last_checked_winning_name(name)
        else:
            last_checked = False

        if not last_checked or (utils.time() - last_checked) >= 30:
            claim = yield self._get_value_for_name(name)
            outpoint = ClaimOutpoint(claim['txid'], claim['n'])
            # TODO: include claim id in the return from getvalueforname to make the
            #       getclaimsforname call unnecessary
            result = yield self._get_claim_info(name, outpoint)
        else:
            log.info("Using cached stream info for lbry://%s", name)
            cache_id = yield self._storage.get_winning_claim_row_id(name)
            result = yield self._storage.get_claim(cache_id)
        defer.returnValue(result)

    def _format_claim_for_return(self, name, claim, metadata=None, meta_version=None):
        result = {}
        result['claim_id'] = claim['claim_id']
        result['amount'] = claim['effective_amount']
        result['height'] = claim['height']
        result['name'] = name
        result['txid'] = claim['txid']
        result['nout'] = claim['nout']
        result['value'] = metadata if metadata else json.loads(claim['value'])
        result['supports'] = [
            {'txid': support['txid'], 'nout': support['nout']} for support in claim['supports']]
        result['meta_version'] = (
            meta_version if meta_version else result['value'].get('ver', '0.0.1'))
        return result

    @defer.inlineCallbacks
    def _get_claim_info(self, name, claim_outpoint):
        claim_id = yield self.get_claimid(name, claim_outpoint['txid'], claim_outpoint['nout'])
        claim = yield self.get_claim(name, claim_id)
        try:
            metadata = Metadata(json.loads(claim['value']))
            meta_ver = metadata.version
        except (TypeError, ValueError, ValidationError):
            metadata = claim['value']
            meta_ver = "Non-compliant"
        result = self._format_claim_for_return(name, claim,
                                               metadata=metadata,
                                               meta_version=meta_ver)
        yield self._save_name_metadata(name, claim_outpoint, claim['claim_id'],
                                       metadata, result['amount'], result['height'])
        log.debug("get claim info lbry://%s metadata: %s, claimid: %s", name, meta_ver,
                 claim['claimId'])
        defer.returnValue(result)

    def get_claims_for_name(self, name):
        d = self._get_claims_for_name(name)
        return d

    def update_metadata(self, new_metadata, old_metadata):
        meta_for_return = old_metadata if isinstance(old_metadata, dict) else {}
        for k in new_metadata:
            meta_for_return[k] = new_metadata[k]
        return defer.succeed(Metadata(meta_for_return))

    def _process_claim_out(self, claim_out):
        claim_out.pop('success')
        claim_out['fee'] = float(claim_out['fee'])
        return claim_out

    @defer.inlineCallbacks
    def claim_name(self, name, bid, metadata):
        """
        Claim a name, or update if name already claimed by user

        @param name: str, name to claim
        @param bid: float, bid amount
        @param metadata: Metadata compliant dict

        @return: Deferred which returns a dict containing below items
            txid - txid of the resulting transaction
            nout - nout of the resulting claim
            fee - transaction fee paid to make claim
            claim_id -  claim id of the claim
        """

        _metadata = Metadata(metadata)
        my_claim = yield self.get_my_claim(name)

        if my_claim:
            is_new_claim = False
            log.info("Updating claim")
            if self.get_balance() < Decimal(bid) - Decimal(my_claim['amount']):
                raise InsufficientFundsError()
            new_metadata = yield self.update_metadata(_metadata, my_claim['value'])
            old_claim_outpoint = ClaimOutpoint(my_claim['txid'], my_claim['nout'])
            claim = yield self._send_name_claim_update(name, my_claim['claim_id'],
                                                       old_claim_outpoint, new_metadata, bid)
            claim['claim_id'] = my_claim['claim_id']
        else:
            is_new_claim = True
            log.info("Making a new claim")
            if self.get_balance() < bid:
                raise InsufficientFundsError()
            claim = yield self._send_name_claim(name, _metadata, bid)

        if not claim['success']:
            msg = 'Claim to name {} failed: {}'.format(name, claim['reason'])
            raise Exception(msg)

        claim = self._process_claim_out(claim)
        claim_outpoint = ClaimOutpoint(claim['txid'], claim['nout'])
        if is_new_claim:
            claim_id = utils.generate_claimid(claim_outpoint)
        else:
            claim_id = claim['claim_id']
        log.info("Saving metadata for lbry://%s (id %s) %s:%i",
                 name, utils.short_hash(claim_id), claim['txid'], claim['nout'])
        yield self._save_name_metadata(name, claim_outpoint, claim_id,
                                       _metadata, int(bid * COIN), self.blockchain_height,
                                       is_mine=True, update=True)
        defer.returnValue(claim)

    @defer.inlineCallbacks
    def abandon_claim(self, txid, nout):
        def _parse_abandon_claim_out(claim_out):
            if not claim_out['success']:
                msg = 'Abandon of {}:{} failed: {}'.format(txid, nout, claim_out['reason'])
                raise Exception(msg)
            claim_out = self._process_claim_out(claim_out)
            log.info("Abandoned claim tx %s (n: %i) --> %s", txid, nout, claim_out)
            return defer.succeed(claim_out)

        claim_outpoint = ClaimOutpoint(txid, nout)
        claim_out = yield self._abandon_claim(claim_outpoint)
        result = yield _parse_abandon_claim_out(claim_out)
        defer.returnValue(result)

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

    @property
    def blockchain_height(self):
        return 0

    def _update_balance(self):
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

    def _send_name_claim(self, name, val, amount):
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

    @property
    def blockchain_height(self):
        server_height = self.network.get_server_height()
        local_height = self.network.get_local_height()
        assert server_height == local_height, Exception("Not caught up with blockchain yet")
        return local_height

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
        path = self.config.get_wallet_path()
        storage = lbryum_wallet.WalletStorage(path)
        wallet = lbryum_wallet.Wallet(storage)
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
    def _run_cmd_as_defer_succeed(self, command_name, *args):
        cmd_runner = self._get_cmd_runner()
        cmd = known_commands[command_name]
        func = getattr(cmd_runner, cmd.name)
        return defer.succeed(func(*args))

    # run commands as a deferToThread,  lbryum commands that only make
    # queries to lbryum server should be run this way
    def _run_cmd_as_defer_to_thread(self, command_name, *args):
        cmd_runner = self._get_cmd_runner()
        cmd = known_commands[command_name]
        func = getattr(cmd_runner, cmd.name)
        return threads.deferToThread(func, *args)

    def _update_balance(self):
        accounts = None
        exclude_claimtrietx = True
        d = self._run_cmd_as_defer_succeed('getbalance', accounts, exclude_claimtrietx)
        d.addCallback(
            lambda result: Decimal(result['confirmed']) + Decimal(result.get('unconfirmed', 0.0)))
        return d

    def get_new_address(self):
        addr = self.wallet.get_unused_address(account=None)
        if addr is None:
            addr = self.wallet.create_new_address()
        d = defer.succeed(addr)
        d.addCallback(self._save_wallet)
        return d

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

    def get_name_claims(self):
        return self._run_cmd_as_defer_succeed('getnameclaims')

    def _get_claims_for_name(self, name):
        return self._run_cmd_as_defer_to_thread('getclaimsforname', name)

    def _send_name_claim(self, name, val, amount):
        broadcast = False
        log.debug("Name claim %s %s %f", name, val, amount)
        d = self._run_cmd_as_defer_succeed('claim', name, json.dumps(val), amount, broadcast)
        d.addCallback(lambda claim_out: self._broadcast_claim_transaction(claim_out))
        return d

    def _send_name_claim_update(self, name, claim_id, claim_outpoint, value, amount):
        metadata = json.dumps(value)
        log.debug("Update %s %d %f %s %s '%s'", claim_outpoint['txid'], claim_outpoint['nout'],
                  amount, name, claim_id, metadata)
        broadcast = False
        d = self._run_cmd_as_defer_succeed('update', claim_outpoint['txid'], claim_outpoint['nout'],
                                           name, claim_id, metadata, amount, broadcast)
        d.addCallback(lambda claim_out: self._broadcast_claim_transaction(claim_out))
        return d

    def _abandon_claim(self, claim_outpoint):
        log.debug("Abandon %s %s" % (claim_outpoint['txid'], claim_outpoint['nout']))
        broadcast = False
        d = self._run_cmd_as_defer_succeed('abandon', claim_outpoint['txid'],
                                           claim_outpoint['nout'], broadcast)
        d.addCallback(lambda claim_out: self._broadcast_claim_transaction(claim_out))
        return d

    def _support_claim(self, name, claim_id, amount):
        log.debug("Support %s %s %f" % (name, claim_id, amount))
        broadcast = False
        d = self._run_cmd_as_defer_succeed('support', name, claim_id, amount, broadcast)
        d.addCallback(lambda claim_out: self._broadcast_claim_transaction(claim_out))
        return d

    def _broadcast_claim_transaction(self, claim_out):
        if 'success' not in claim_out:
            raise Exception('Unexpected claim command output:{}'.format(claim_out))
        if claim_out['success']:
            d = self._broadcast_transaction(claim_out['tx'])
            d.addCallback(lambda _: claim_out)
            return d
        else:
            return defer.succeed(claim_out)

    def _broadcast_transaction(self, raw_tx):
        def _log_tx(r):
            log.debug("Broadcast tx: %s", r)
            return r

        d = self._run_cmd_as_defer_to_thread('broadcast', raw_tx)
        d.addCallback(_log_tx)
        d.addCallback(
            lambda r: r if len(r) == 64 else defer.fail(Exception("Transaction rejected")))
        return d

    def _do_send_many(self, payments_to_send):
        def broadcast_send_many(paytomany_out):
            if 'hex' not in paytomany_out:
                raise Exception('Unexpected paytomany output:{}'.format(paytomany_out))
            return self._broadcast_transaction(paytomany_out['hex'])

        log.debug("Doing send many. payments to send: %s", str(payments_to_send))
        d = self._run_cmd_as_defer_succeed('paytomany', payments_to_send.iteritems())
        d.addCallback(lambda out: broadcast_send_many(out))
        return d

    @defer.inlineCallbacks
    def _get_value_for_name(self, name):
        height_to_check = self.network.get_local_height() - RECOMMENDED_CLAIMTRIE_HASH_CONFIRMS + 1
        if height_to_check < 0:
            msg = "Height to check is less than 0, blockchain headers are likely not initialized"
            raise Exception(msg)
        block_header = self.network.blockchain.read_header(height_to_check)
        block_hash = self.network.blockchain.hash_header(block_header)

        proof = yield self._run_cmd_as_defer_to_thread('requestvalueforname', name, block_hash)
        result = Commands._verify_proof(name, block_header['claim_trie_root'], proof)
        if not result.get('error', False):
            try:
                metadata = Metadata(json.loads(result['value']))
            except (KeyError, TypeError, ValueError, ValidationError):
                metadata = None
            txid = result['txid']
            n = result['n']
            amount = result['amount']
            height = result['height']
            claim_outpoint = ClaimOutpoint(txid, n)
            claim_id = yield self.get_claimid(name, txid, n)
            yield self._save_name_metadata(name, claim_outpoint, claim_id, metadata, amount, height)
            yield self._storage.set_winning_claim(name, claim_outpoint)
        else:
            log.warning("Failed to get value for lbry://%s : %s", name, result['error'])
            raise Exception(result['error'])
        defer.returnValue(result)

    def get_claims_from_tx(self, txid):
        return self._run_cmd_as_defer_to_thread('getclaimsfromtx', txid)

    def _get_balance_for_address(self, address):
        return defer.succeed(Decimal(self.wallet.get_addr_received(address)) / COIN)

    def get_nametrie(self):
        return self._run_cmd_as_defer_to_thread('getclaimtrie')

    def _get_history(self):
        return self._run_cmd_as_defer_succeed('history')

    def _address_is_mine(self, address):
        return self._run_cmd_as_defer_succeed('ismine', address)

    def get_pub_keys(self, wallet):
        return self._run_cmd_as_defer_succeed('getpubkyes', wallet)

    def _save_wallet(self, val):
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
            d = self.wallet.get_new_address_for_peer(self.peer)
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
