import sys
from lbrynet.interfaces import IRequestCreator, IQueryHandlerFactory, IQueryHandler, ILBRYWallet
from lbrynet.core.client.ClientRequest import ClientRequest
from lbrynet.core.Error import UnknownNameError, InvalidStreamInfoError, RequestCanceledError
from lbrynet.core.Error import InsufficientFundsError
from lbrynet.core.sqlite_helpers import rerun_if_locked
from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
from twisted.internet import threads, reactor, defer, task
from twisted.python.failure import Failure
from twisted.enterprise import adbapi
from collections import defaultdict, deque
from zope.interface import implements
from decimal import Decimal
import datetime
import logging
import json
import subprocess
import socket
import time
import os

log = logging.getLogger(__name__)
alert = logging.getLogger("lbryalert." + __name__)


class ReservedPoints(object):
    def __init__(self, identifier, amount):
        self.identifier = identifier
        self.amount = amount


def _catch_connection_error(f):
    def w(*args):
        try:
            return f(*args)
        except socket.error:
            raise ValueError("Unable to connect to an lbrycrd server. Make sure an lbrycrd server " +
                             "is running and that this application can connect to it.")
    return w


class LBRYcrdWallet(object):
    """This class implements the LBRYWallet interface for the LBRYcrd payment system"""
    implements(ILBRYWallet)

    def __init__(self, db_dir, wallet_dir=None, wallet_conf=None, lbrycrdd_path=None):

        self.db_dir = db_dir
        self.db = None
        self.next_manage_call = None
        self.wallet_balance = Decimal(0.0)
        self.total_reserved_points = Decimal(0.0)
        self.peer_addresses = {}  # {Peer: string}
        self.queued_payments = defaultdict(Decimal)  # {address(string): amount(Decimal)}
        self.expected_balances = defaultdict(Decimal)  # {address(string): amount(Decimal)}
        self.current_address_given_to_peer = {}  # {Peer: address(string)}
        self.expected_balance_at_time = deque()  # (Peer, address(string), amount(Decimal), time(datetime), count(int),
                                                 # incremental_amount(float))
        self.max_expected_payment_time = datetime.timedelta(minutes=3)
        self.stopped = True
        self.started_lbrycrdd = False
        self.wallet_dir = wallet_dir
        self.wallet_conf = wallet_conf
        self.lbrycrdd = None
        self.manage_running = False
        self.lbrycrdd_path = lbrycrdd_path

        settings = self.get_rpc_conf()
        rpc_user = settings["username"]
        rpc_pass = settings["password"]
        rpc_port = settings["rpc_port"]
        rpc_url = "127.0.0.1"
        self.rpc_conn_string = "http://%s:%s@%s:%s" % (rpc_user, rpc_pass, rpc_url, str(rpc_port))

    def start(self):

        def make_connection():
            alert.info("Connecting to lbrycrdd...")
            if self.lbrycrdd_path is not None:
                self._start_daemon()
            self._get_info()
            log.info("Connected!")
            alert.info("Connected to lbrycrdd.")

        def start_manage():
            self.stopped = False
            self.manage()
            return True

        d = self._open_db()
        d.addCallback(lambda _: threads.deferToThread(make_connection))
        d.addCallback(lambda _: start_manage())
        return d

    def stop(self):

        def log_stop_error(err):
            log.error("An error occurred stopping the wallet. %s", err.getTraceback())

        self.stopped = True
        # If self.next_manage_call is None, then manage is currently running or else
        # start has not been called, so set stopped and do nothing else.
        if self.next_manage_call is not None:
            self.next_manage_call.cancel()
            self.next_manage_call = None

        d = self.manage()
        d.addErrback(log_stop_error)
        if self.lbrycrdd_path is not None:
            d.addCallback(lambda _: self._stop_daemon())
            d.addErrback(log_stop_error)
        return d

    def manage(self):
        log.info("Doing manage")
        self.next_manage_call = None
        have_set_manage_running = [False]

        def check_if_manage_running():

            d = defer.Deferred()

            def fire_if_not_running():
                if self.manage_running is False:
                    self.manage_running = True
                    have_set_manage_running[0] = True
                    d.callback(True)
                else:
                    task.deferLater(reactor, 1, fire_if_not_running)

            fire_if_not_running()
            return d

        d = check_if_manage_running()

        d.addCallback(lambda _: self._check_expected_balances())

        d.addCallback(lambda _: self._send_payments())

        d.addCallback(lambda _: threads.deferToThread(self._get_wallet_balance))

        def set_wallet_balance(balance):
            self.wallet_balance = balance

        d.addCallback(set_wallet_balance)

        def set_next_manage_call():
            if not self.stopped:
                self.next_manage_call = reactor.callLater(60, self.manage)

        d.addCallback(lambda _: set_next_manage_call())

        def log_error(err):
            log.error("Something went wrong during manage. Error message: %s", err.getErrorMessage())
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

    def get_balance(self):
        d = threads.deferToThread(self._get_wallet_balance)
        return d

    def reserve_points(self, identifier, amount):
        """
        Ensure a certain amount of points are available to be sent as payment, before the service is rendered

        @param identifier: The peer to which the payment will ultimately be sent

        @param amount: The amount of points to reserve

        @return: A ReservedPoints object which is given to send_points once the service has been rendered
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
        log.info("ordering that %s points be sent to %s", str(rounded_amount),
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
        log.info("Ordering that %s points be sent to %s", str(rounded_amount),
                 str(address))
        return defer.succeed(True)

    def add_expected_payment(self, peer, amount):
        """Increase the number of points expected to be paid by a peer"""
        rounded_amount = Decimal(str(round(amount, 8)))
        assert(peer in self.current_address_given_to_peer)
        address = self.current_address_given_to_peer[peer]
        log.info("expecting a payment at address %s in the amount of %s", str(address), str(rounded_amount))
        self.expected_balances[address] += rounded_amount
        expected_balance = self.expected_balances[address]
        expected_time = datetime.datetime.now() + self.max_expected_payment_time
        self.expected_balance_at_time.append((peer, address, expected_balance, expected_time, 0, amount))
        peer.update_stats('expected_points', amount)

    def update_peer_address(self, peer, address):
        self.peer_addresses[peer] = address

    def get_new_address_for_peer(self, peer):
        def set_address_for_peer(address):
            self.current_address_given_to_peer[peer] = address
            return address
        d = threads.deferToThread(self._get_new_address)
        d.addCallback(set_address_for_peer)
        return d

    def get_stream_info_for_name(self, name):

        def get_stream_info_from_value(result):
            r_dict = {}
            if 'value' in result:
                value = result['value']
                try:
                    value_dict = json.loads(value)
                except ValueError:
                    return Failure(InvalidStreamInfoError(name))
                known_fields = ['stream_hash', 'name', 'description', 'key_fee', 'key_fee_address', 'thumbnail']
                for field in known_fields:
                    if field in value_dict:
                        r_dict[field] = value_dict[field]
                if 'stream_hash' in r_dict and 'txid' in result:
                    d = self._save_name_metadata(name, r_dict['stream_hash'], str(result['txid']))
                else:
                    d = defer.succeed(True)
                d.addCallback(lambda _: r_dict)
                return d
            return Failure(UnknownNameError(name))

        d = threads.deferToThread(self._get_value_for_name, name)
        d.addCallback(get_stream_info_from_value)
        return d

    def claim_name(self, name, sd_hash, amount, description=None, key_fee=None,
                    key_fee_address=None, thumbnail=None, content_license=None):
        value = {"stream_hash": sd_hash}
        if description is not None:
            value['description'] = description
        if key_fee is not None:
            value['key_fee'] = key_fee
        if key_fee_address is not None:
            value['key_fee_address'] = key_fee_address
        if thumbnail is not None:
            value['thumbnail'] = thumbnail
        if content_license is not None:
            value['content_license'] = content_license

        d = threads.deferToThread(self._claim_name, name, json.dumps(value), amount)

        def _save_metadata(txid):
            d = self._save_name_metadata(name, sd_hash, txid)
            d.addCallback(lambda _: txid)
            return d

        d.addCallback(_save_metadata)
        return d

    def get_name_and_validity_for_sd_hash(self, sd_hash):
        d = self._get_claim_metadata_for_sd_hash(sd_hash)
        d.addCallback(lambda name_txid: threads.deferToThread(self._get_status_of_claim, name_txid[1], name_txid[0], sd_hash) if name_txid is not None else None)
        return d

    def get_available_balance(self):
        return float(self.wallet_balance - self.total_reserved_points)

    def get_new_address(self):
        return threads.deferToThread(self._get_new_address)

    def check_first_run(self):
        d = threads.deferToThread(self._get_wallet_balance)
        d.addCallback(lambda bal: threads.deferToThread(self._get_num_addresses) if bal == 0 else 2)
        d.addCallback(lambda num_addresses: True if num_addresses <= 1 else False)
        return d

    def get_most_recent_blocktime(self):
        return threads.deferToThread(self._get_best_block_time)

    def get_rpc_conf(self):
        settings = {"username": "rpcuser",
                    "password": "rpcpassword",
                    "rpc_port": 8332}
        if os.path.exists(self.wallet_conf):
            conf = open(self.wallet_conf)
            for l in conf:
                if l.startswith("rpcuser="):
                    settings["username"] = l[8:].rstrip('\n')
                if l.startswith("rpcpassword="):
                    settings["password"] = l[12:].rstrip('\n')
                if l.startswith("rpcport="):
                    settings["rpc_port"] = int(l[8:].rstrip('\n'))
        return settings

    def _get_rpc_conn(self):
        return AuthServiceProxy(self.rpc_conn_string)

    def get_rpc_conn_x(self):
        return AuthServiceProxy(self.rpc_conn_string)

    def _start_daemon(self):

        tries = 0
        try:
            rpc_conn = self._get_rpc_conn()
            rpc_conn.getinfo()
            log.info("lbrycrdd was already running when LBRYcrdWallet was started.")
            return
        except (socket.error, JSONRPCException):
            tries += 1
            log.info("lbrcyrdd was not running when LBRYcrdWallet was started. Attempting to start it.")

        try:
            if os.name == "nt":
                si = subprocess.STARTUPINFO
                si.dwFlags = subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = subprocess.SW_HIDE
                self.lbrycrdd = subprocess.Popen([self.lbrycrdd_path, "-datadir=%s" % self.wallet_dir,
                                                  "-conf=%s" % self.wallet_conf], startupinfo=si)
            else:
                if sys.platform == 'darwin':
                    os.chdir("/Applications/LBRY.app/Contents/Resources")
                self.lbrycrdd = subprocess.Popen([self.lbrycrdd_path, "-datadir=%s" % self.wallet_dir,
                                                  "-conf=%s" % self.wallet_conf])
            self.started_lbrycrdd = True
        except OSError:
            import traceback
            log.error("Couldn't launch lbrycrdd at path %s: %s", self.lbrycrdd_path, traceback.format_exc())
            raise ValueError("Couldn't launch lbrycrdd. Tried %s" % self.lbrycrdd_path)

        while tries < 6:
            try:
                rpc_conn = self._get_rpc_conn()
                rpc_conn.getinfo()
                break
            except (socket.error, JSONRPCException):
                tries += 1
                log.warning("Failed to connect to lbrycrdd.")
                if tries < 6:
                    time.sleep(2 ** tries)
                    log.warning("Trying again in %d seconds", 2 ** tries)
                else:
                    log.warning("Giving up.")
        else:
            self.lbrycrdd.terminate()
            raise ValueError("Couldn't open lbrycrdd")

    def _stop_daemon(self):
        if self.lbrycrdd is not None and self.started_lbrycrdd is True:
            alert.info("Stopping lbrycrdd...")
            d = threads.deferToThread(self._rpc_stop)
            d.addCallback(lambda _: alert.info("Stopped lbrycrdd."))
            return d
        return defer.succeed(True)

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
            d = threads.deferToThread(self._check_expected_balance, balance_to_check)
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

    @_catch_connection_error
    def _check_expected_balance(self, expected_balance):
        rpc_conn = self._get_rpc_conn()
        log.info("Checking balance of address %s", str(expected_balance[1]))
        balance = rpc_conn.getreceivedbyaddress(expected_balance[1])
        log.debug("received balance: %s", str(balance))
        log.debug("expected balance: %s", str(expected_balance[2]))
        return balance >= expected_balance[2]

    def _send_payments(self):
        log.info("Trying to send payments, if there are any to be sent")

        def do_send(payments):
            rpc_conn = self._get_rpc_conn()
            rpc_conn.sendmany("", payments)

        payments_to_send = {}
        for address, points in self.queued_payments.items():
            log.info("Should be sending %s points to %s", str(points), str(address))
            payments_to_send[address] = float(points)
            self.total_reserved_points -= points
            self.wallet_balance -= points
            del self.queued_payments[address]
        if payments_to_send:
            log.info("Creating a transaction with outputs %s", str(payments_to_send))
            return threads.deferToThread(do_send, payments_to_send)
        log.info("There were no payments to send")
        return defer.succeed(True)

    @_catch_connection_error
    def _get_info(self):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getinfo()

    @_catch_connection_error
    def _get_wallet_balance(self):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getbalance("")

    @_catch_connection_error
    def _get_new_address(self):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getnewaddress()

    @_catch_connection_error
    def _get_value_for_name(self, name):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getvalueforname(name)

    @_catch_connection_error
    def _claim_name(self, name, value, amount):
        rpc_conn = self._get_rpc_conn()
        try:
            return str(rpc_conn.claimname(name, value, amount))
        except JSONRPCException as e:
            if 'message' in e.error and e.error['message'] == "Insufficient funds":
                raise InsufficientFundsError()
            elif 'message' in e.error:
                raise ValueError(e.error['message'])

    @_catch_connection_error
    def _get_status_of_claim(self, txhash, name, sd_hash):
        rpc_conn = self._get_rpc_conn()
        claims = rpc_conn.getclaimsfortx(txhash)
        if claims is None:
            claims = []
        for claim in claims:
            if 'in claim trie' in claim:
                if 'name' in claim and str(claim['name']) == name and 'value' in claim:
                    try:
                        value_dict = json.loads(claim['value'])
                    except ValueError:
                        return None
                    if 'stream_hash' in value_dict and str(value_dict['stream_hash']) == sd_hash:
                        if 'is controlling' in claim and claim['is controlling']:
                            return name, "valid"
                        if claim['in claim trie']:
                            return name, "invalid"
                        if 'in queue' in claim and claim['in queue']:
                            return name, "pending"
                        return name, "unconfirmed"
        return None

    @_catch_connection_error
    def _get_num_addresses(self):
        rpc_conn = self._get_rpc_conn()
        return len(rpc_conn.getaddressesbyaccount(""))

    @_catch_connection_error
    def _get_best_block_time(self):
        rpc_conn = self._get_rpc_conn()
        best_block_hash = rpc_conn.getbestblockhash()
        block = rpc_conn.getblock(best_block_hash)
        if 'time' in block:
            return block['time']
        raise ValueError("Could not get a block time")


    @_catch_connection_error
    def _rpc_stop(self):
        # check if our lbrycrdd is actually running, or if we connected to one that was already
        # running and ours failed to start
        if self.lbrycrdd.poll() is None:
            rpc_conn = self._get_rpc_conn()
            rpc_conn.stop()
            self.lbrycrdd.wait()

    def _open_db(self):
        self.db = adbapi.ConnectionPool('sqlite3', os.path.join(self.db_dir, "blockchainname.db"),
                                        check_same_thread=False)
        return self.db.runQuery("create table if not exists name_metadata (" +
                                "    name text, " +
                                "    txid text, " +
                                "    sd_hash text)")

    def _save_name_metadata(self, name, sd_hash, txid):
        d = self.db.runQuery("insert into name_metadata values (?, ?, ?)",
                             (name, txid, sd_hash))
        return d

    def _get_claim_metadata_for_sd_hash(self, sd_hash):
        d = self.db.runQuery("select name, txid from name_metadata where sd_hash=?", (sd_hash,))
        d.addCallback(lambda r: r[0] if len(r) else None)
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