import sys
from lbrynet.interfaces import IRequestCreator, IQueryHandlerFactory, IQueryHandler, ILBRYWallet
from lbrynet.core.client.ClientRequest import ClientRequest
from lbrynet.core.Error import UnknownNameError, InvalidStreamInfoError, RequestCanceledError
from lbrynet.core.Error import InsufficientFundsError
from lbrynet.core.sqlite_helpers import rerun_if_locked

from lbryum import SimpleConfig, Network
from lbryum.bitcoin import COIN, TYPE_ADDRESS
from lbryum.wallet import WalletStorage, Wallet
from lbryum.commands import known_commands, Commands
from lbryum.transaction import Transaction

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


class LBRYWallet(object):
    """This class implements the LBRYWallet interface for the LBRYcrd payment system"""
    implements(ILBRYWallet)

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
        self.expected_balance_at_time = deque()  # (Peer, address(string), amount(Decimal), time(datetime), count(int),
                                                 # incremental_amount(float))
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
        d.addCallback(lambda _: self._start())
        d.addCallback(lambda _: start_manage())
        return d

    @staticmethod
    def log_stop_error(err):
        log.error("An error occurred stopping the wallet: %s", err.getTraceback())

    def stop(self):

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
                    log.info("Got a new balance: %s", str(balance))
                self.wallet_balance = balance

            d.addCallback(set_wallet_balance)
            return d

        d.addCallback(lambda should_run: do_manage() if should_run else None)

        def set_next_manage_call():
            if not self.stopped:
                self.next_manage_call = reactor.callLater(self._balance_refresh_time, self.manage)

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
        d = self.get_new_address()
        d.addCallback(set_address_for_peer)
        return d

    def _send_payments(self):
        payments_to_send = {}
        for address, points in self.queued_payments.items():
            log.info("Should be sending %s points to %s", str(points), str(address))
            payments_to_send[address] = points
            self.total_reserved_points -= points
            self.wallet_balance -= points
            del self.queued_payments[address]
        if payments_to_send:
            log.info("Creating a transaction with outputs %s", str(payments_to_send))
            d = self._do_send_many(payments_to_send)
            d.addCallback(lambda txid: log.debug("Sent transaction %s", txid))
            return d
        log.info("There were no payments to send")
        return defer.succeed(True)

    def get_stream_info_for_name(self, name):
        d = self._get_value_for_name(name)
        d.addCallback(self._get_stream_info_from_value, name)
        return d

    def get_stream_info_from_txid(self, name, txid):
        d = self.get_claims_from_tx(txid)

        def get_claim_for_name(claims):
            for claim in claims:
                if claim['name'] == name:
                    claim['txid'] = txid
                    return claim
            return Failure(UnknownNameError(name))

        d.addCallback(get_claim_for_name)
        d.addCallback(self._get_stream_info_from_value, name)
        return d

    def _get_stream_info_from_value(self, result, name):
        r_dict = {}
        if 'value' in result:
            value = result['value']
            try:
                value_dict = json.loads(value)
            except (ValueError, TypeError):
                return Failure(InvalidStreamInfoError(name))
            known_fields = ['stream_hash', 'name', 'description', 'key_fee', 'key_fee_address', 'thumbnail',
                            'content_license', 'sources', 'fee', 'author']
            known_sources = ['lbry_sd_hash', 'btih', 'url']
            known_fee_types = {'LBC': ['amount', 'address']}
            for field in known_fields:
                if field in value_dict:
                    if field == 'sources':
                        for source in known_sources:
                            if source in value_dict[field]:
                                if source == 'lbry_sd_hash':
                                    r_dict['stream_hash'] = value_dict[field][source]
                                else:
                                    r_dict[source] = value_dict[field][source]
                    elif field == 'fee':
                        fee = value_dict['fee']
                        if 'type' in fee:
                            if fee['type'] in known_fee_types:
                                fee_fields = known_fee_types[fee['type']]
                                if all([f in fee for f in fee_fields]):
                                    r_dict['key_fee'] = fee['amount']
                                    r_dict['key_fee_address'] = fee['address']
                                else:
                                    for f in ['key_fee', 'key_fee_address']:
                                        if f in r_dict:
                                            del r_dict[f]
                    else:
                        r_dict[field] = value_dict[field]
            if 'stream_hash' in r_dict and 'txid' in result:
                d = self._save_name_metadata(name, r_dict['stream_hash'], str(result['txid']))
            else:
                d = defer.succeed(True)
            d.addCallback(lambda _: r_dict)
            return d
        elif 'error' in result:
            log.warning("Got an error looking up a name: %s", result['error'])
        return Failure(UnknownNameError(name))

    def claim_name(self, name, sd_hash, amount, description=None, key_fee=None,
                   key_fee_address=None, thumbnail=None, content_license=None, author=None, sources=None):
        value = {"sources": {'lbry_sd_hash': sd_hash}}
        if description is not None:
            value['description'] = description
        if key_fee is not None and key_fee_address is not None:
            value['fee'] = {'type': 'LBC', 'amount': key_fee, 'address': key_fee_address}
        if thumbnail is not None:
            value['thumbnail'] = thumbnail
        if content_license is not None:
            value['content_license'] = content_license
        if author is not None:
            value['author'] = author
        if isinstance(sources, dict):
            sources['lbry_sd_hash'] = sd_hash
            value['sources'] = sources

        d = self._send_name_claim(name, json.dumps(value), amount)

        def _save_metadata(txid):
            d = self._save_name_metadata(name, sd_hash, txid)
            d.addCallback(lambda _: txid)
            return d

        d.addCallback(_save_metadata)
        return d

    def abandon_name(self, txid):
        d1 = self.get_new_address()
        d2 = self.get_claims_from_tx(txid)

        def get_txout_of_claim(claims):
            for claim in claims:
                if 'name' in claim and 'nOut' in claim:
                    return claim['nOut']
            return defer.fail(ValueError("No claims in tx"))

        def get_value_of_txout(nOut):
            d = self._get_raw_tx(txid)
            d.addCallback(self._get_decoded_tx)
            d.addCallback(lambda tx: tx['vout'][nOut]['value'])
            return d

        d2.addCallback(get_txout_of_claim)
        d2.addCallback(get_value_of_txout)
        dl = defer.DeferredList([d1, d2], consumeErrors=True)

        def abandon(results):
            if results[0][0] and results[1][0]:
                address = results[0][1]
                amount = results[1][1]
                return self._send_abandon(txid, address, amount)
            elif results[0][0] is False:
                return defer.fail(Failure(ValueError("Couldn't get a new address")))
            else:
                return results[1][1]

        dl.addCallback(abandon)
        return dl

    def get_tx(self, txid):
        d = self._get_raw_tx(txid)
        d.addCallback(self._get_decoded_tx)
        return d

    # def update_name(self, name_value):
    #     return self._update_name(name_value)

    def get_name_and_validity_for_sd_hash(self, sd_hash):
        d = self._get_claim_metadata_for_sd_hash(sd_hash)
        d.addCallback(lambda name_txid: self._get_status_of_claim(name_txid[1], name_txid[0], sd_hash) if name_txid is not None else None)
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

    def _get_status_of_claim(self, txid, name, sd_hash):
        d = self.get_claims_from_tx(txid)

        def get_status(claims):
            if claims is None:
                claims = []
            for claim in claims:
                if 'in claim trie' in claim:
                    if 'name' in claim and str(claim['name']) == name and 'value' in claim:
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
            log.info("Checking balance of address %s", str(balance_to_check[1]))
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

    def _check_first_run(self):
        return defer.fail(NotImplementedError())

    def _get_raw_tx(self, txid):
        return defer.fail(NotImplementedError())

    def _send_name_claim(self, name, val, amount):
        return defer.fail(NotImplementedError())

    def _get_decoded_tx(self, raw_tx):
        return defer.fail(NotImplementedError())

    def _send_abandon(self, txid, address, amount):
        return defer.fail(NotImplementedError())

    def _do_send_many(self, payments_to_send):
        return defer.fail(NotImplementedError())

    def _get_value_for_name(self, name):
        return defer.fail(NotImplementedError())

    def get_claims_from_tx(self, txid):
        return defer.fail(NotImplementedError())

    def _get_balance_for_address(self, address):
        return defer.fail(NotImplementedError())

    def _start(self):
        pass

    def _stop(self):
        pass


class LBRYcrdWallet(LBRYWallet):
    def __init__(self, db_dir, wallet_dir=None, wallet_conf=None, lbrycrdd_path=None):
        LBRYWallet.__init__(self, db_dir)
        self.started_lbrycrdd = False
        self.wallet_dir = wallet_dir
        self.wallet_conf = wallet_conf
        self.lbrycrdd = None
        self.lbrycrdd_path = lbrycrdd_path

        settings = self._get_rpc_conf()
        rpc_user = settings["username"]
        rpc_pass = settings["password"]
        rpc_port = settings["rpc_port"]
        rpc_url = "127.0.0.1"
        self.rpc_conn_string = "http://%s:%s@%s:%s" % (rpc_user, rpc_pass, rpc_url, str(rpc_port))

    def _start(self):
        return threads.deferToThread(self._make_connection)

    def _stop(self):
        if self.lbrycrdd_path is not None:
            return self._stop_daemon()

    def _make_connection(self):
        alert.info("Connecting to lbrycrdd...")
        if self.lbrycrdd_path is not None:
            self._start_daemon()
        self._get_info_rpc()
        log.info("Connected!")
        alert.info("Connected to lbrycrdd.")

    def _get_rpc_conf(self):
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

    def _check_first_run(self):
        d = self.get_balance()
        d.addCallback(lambda bal: threads.deferToThread(self._get_num_addresses_rpc) if bal == 0 else 2)
        d.addCallback(lambda num_addresses: True if num_addresses <= 1 else False)
        return d

    def get_new_address(self):
        return threads.deferToThread(self._get_new_address_rpc)

    def get_balance(self):
        return threads.deferToThread(self._get_wallet_balance_rpc)

    def get_most_recent_blocktime(self):
        d = threads.deferToThread(self._get_best_blockhash_rpc)
        d.addCallback(lambda blockhash: threads.deferToThread(self._get_block_rpc, blockhash))
        d.addCallback(
            lambda block: block['time'] if 'time' in block else Failure(ValueError("Could not get a block time")))
        return d

    def get_name_claims(self):
        return threads.deferToThread(self._get_name_claims_rpc)

    def get_block(self, blockhash):
        return threads.deferToThread(self._get_block_rpc, blockhash)

    def get_best_blockhash(self):
        d = threads.deferToThread(self._get_blockchain_info_rpc)
        d.addCallback(lambda blockchain_info: blockchain_info['bestblockhash'])
        return d

    def get_nametrie(self):
        return threads.deferToThread(self._get_nametrie_rpc)

    def start_miner(self):
        d = threads.deferToThread(self._get_gen_status_rpc)
        d.addCallback(lambda status: threads.deferToThread(self._set_gen_status_rpc, True) if not status
                      else "Miner was already running")
        return d

    def stop_miner(self):
        d = threads.deferToThread(self._get_gen_status_rpc)
        d.addCallback(lambda status: threads.deferToThread(self._set_gen_status_rpc, False) if status
                      else "Miner wasn't running")
        return d

    def get_miner_status(self):
        return threads.deferToThread(self._get_gen_status_rpc)

    def _get_balance_for_address(self, address):
        return threads.deferToThread(self._get_balance_for_address_rpc, address)

    def _do_send_many(self, payments_to_send):
        outputs = {address: float(points) for address, points in payments_to_send.iteritems()}
        return threads.deferToThread(self._do_send_many_rpc, outputs)

    def _send_name_claim(self, name, value, amount):
        return threads.deferToThread(self._send_name_claim_rpc, name, value, amount)

    def _get_raw_tx(self, txid):
        return threads.deferToThread(self._get_raw_tx_rpc, txid)

    def _get_decoded_tx(self, raw_tx):
        return threads.deferToThread(self._get_decoded_tx_rpc, raw_tx)

    def _send_abandon(self, txid, address, amount):
        return threads.deferToThread(self._send_abandon_rpc, txid, address, amount)

    def get_claims_from_tx(self, txid):
        return threads.deferToThread(self._get_claims_from_tx_rpc, txid)

    def _get_value_for_name(self, name):
        return threads.deferToThread(self._get_value_for_name_rpc, name)

    def _get_rpc_conn(self):
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
            d = threads.deferToThread(self._stop_rpc)
            d.addCallback(lambda _: alert.info("Stopped lbrycrdd."))
            return d
        return defer.succeed(True)

    @_catch_connection_error
    def _get_balance_for_address_rpc(self, address):
        rpc_conn = self._get_rpc_conn()
        balance = rpc_conn.getreceivedbyaddress(address)
        log.debug("received balance for %s: %s", str(address), str(balance))
        return balance

    @_catch_connection_error
    def _do_send_many_rpc(self, payments):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.sendmany("", payments)

    @_catch_connection_error
    def _get_info_rpc(self):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getinfo()

    @_catch_connection_error
    def _get_name_claims_rpc(self):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.listnameclaims()

    @_catch_connection_error
    def _get_gen_status_rpc(self):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getgenerate()

    @_catch_connection_error
    def _set_gen_status_rpc(self, b):
        if b:
            log.info("Starting miner")
        else:
            log.info("Stopping miner")
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.setgenerate(b)

    @_catch_connection_error
    def _get_raw_tx_rpc(self, txid):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getrawtransaction(txid)

    @_catch_connection_error
    def _get_decoded_tx_rpc(self, raw):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.decoderawtransaction(raw)

    @_catch_connection_error
    def _send_abandon_rpc(self, txid, address, amount):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.abandonname(txid, address, amount)

    @_catch_connection_error
    def _get_blockchain_info_rpc(self):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getblockchaininfo()

    @_catch_connection_error
    def _get_block_rpc(self, blockhash):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getblock(blockhash)

    @_catch_connection_error
    def _get_claims_from_tx_rpc(self, txid):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getclaimsfortx(txid)

    @_catch_connection_error
    def _get_nametrie_rpc(self):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getnametrie()

    @_catch_connection_error
    def _get_wallet_balance_rpc(self):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getbalance("")

    @_catch_connection_error
    def _get_new_address_rpc(self):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getnewaddress()

    @_catch_connection_error
    def _get_value_for_name_rpc(self, name):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getvalueforname(name)

    # def _update_name_rpc(self, name_value):
    #     rpc_conn = self._get_rpc_conn()
    #     return rpc_conn.updatename(name_value)

    @_catch_connection_error
    def _send_name_claim_rpc(self, name, value, amount):
        rpc_conn = self._get_rpc_conn()
        try:
            return str(rpc_conn.claimname(name, value, amount))
        except JSONRPCException as e:
            if 'message' in e.error and e.error['message'] == "Insufficient funds":
                raise InsufficientFundsError()
            elif 'message' in e.error:
                raise ValueError(e.error['message'])

    @_catch_connection_error
    def _get_num_addresses_rpc(self):
        rpc_conn = self._get_rpc_conn()
        return len(rpc_conn.getaddressesbyaccount(""))

    @_catch_connection_error
    def _get_best_blockhash_rpc(self):
        rpc_conn = self._get_rpc_conn()
        return rpc_conn.getbestblockhash()

    @_catch_connection_error
    def _stop_rpc(self):
        # check if our lbrycrdd is actually running, or if we connected to one that was already
        # running and ours failed to start
        if self.lbrycrdd.poll() is None:
            rpc_conn = self._get_rpc_conn()
            rpc_conn.stop()
            self.lbrycrdd.wait()


class LBRYumWallet(LBRYWallet):

    def __init__(self, db_dir):
        LBRYWallet.__init__(self, db_dir)
        self.config = None
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
            self.config = SimpleConfig()
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
            storage = WalletStorage(path)
            wallet = Wallet(storage)
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
            local_height = self.network.get_local_height()
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


        self._catch_up_check = task.LoopingCall(check_caught_up)

        d = threads.deferToThread(get_wallet)
        d.addCallback(self._save_wallet)
        d.addCallback(lambda _: self.wallet.start_threads(self.network))
        d.addCallback(lambda _: self._catch_up_check.start(.1))
        d.addCallback(lambda _: blockchain_caught_d)
        return d

    def _get_cmd_runner(self):
        self.cmd_runner = Commands(self.config, self.wallet, self.network)

    def get_balance(self):
        cmd = known_commands['getbalance']
        func = getattr(self.cmd_runner, cmd.name)
        d = threads.deferToThread(func)
        d.addCallback(lambda result: result['unmatured'] if 'unmatured' in result else result['confirmed'])
        d.addCallback(Decimal)
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

    def _send_name_claim(self, name, val, amount):
        def send_claim(address):
            cmd = known_commands['claimname']
            func = getattr(self.cmd_runner, cmd.name)
            return threads.deferToThread(func, address, amount, name, val)
        d = self.get_new_address()
        d.addCallback(send_claim)
        d.addCallback(self._broadcast_transaction)
        return d

    def _get_decoded_tx(self, raw_tx):
        tx = Transaction(raw_tx)
        decoded_tx = {}
        decoded_tx['vout'] = []
        for output in tx.outputs():
            out = {}
            out['value'] = Decimal(output[2]) / Decimal(COIN)
            decoded_tx['vout'].append(out)
        return decoded_tx

    def _send_abandon(self, txid, address, amount):
        log.info("Abandon " + str(txid) + " " + str(address) + " " + str(amount))
        cmd = known_commands['abandonclaim']
        func = getattr(self.cmd_runner, cmd.name)
        d = threads.deferToThread(func, txid, address, amount)
        d.addCallback(self._broadcast_transaction)
        return d

    def _broadcast_transaction(self, raw_tx):
        log.info("Broadcast: " + str(raw_tx))
        cmd = known_commands['broadcast']
        func = getattr(self.cmd_runner, cmd.name)
        d = threads.deferToThread(func, raw_tx)
        d.addCallback(self._save_wallet)
        return d

    def _do_send_many(self, payments_to_send):
        log.warning("Doing send many. payments to send: %s", str(payments_to_send))
        outputs = [(TYPE_ADDRESS, address, int(amount*COIN)) for address, amount in payments_to_send.iteritems()]
        d = threads.deferToThread(self.wallet.mktx, outputs, None, self.config)
        d.addCallback(lambda tx: threads.deferToThread(self.wallet.sendtx, tx))
        d.addCallback(self._save_wallet)
        return d

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

    def get_history(self):
        cmd = known_commands['history']
        func = getattr(self.cmd_runner, cmd.name)
        return threads.deferToThread(func)

    def get_tx_json(self, txid):
        def _decode(raw_tx):
            tx = Transaction(raw_tx).deserialize()
            decoded_tx = {}
            for txkey in tx.keys():
                if isinstance(tx[txkey], list):
                    decoded_tx[txkey] = []
                    for i in tx[txkey]:
                        tmp = {}
                        for k in i.keys():
                            if isinstance(i[k], Decimal):
                                tmp[k] = float(i[k] / 1e8)
                            else:
                                tmp[k] = i[k]
                        decoded_tx[txkey].append(tmp)
                else:
                    decoded_tx[txkey] = tx[txkey]
            return decoded_tx

        d = self._get_raw_tx(txid)
        d.addCallback(_decode)
        return d

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