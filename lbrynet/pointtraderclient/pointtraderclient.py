from lbrynet import conf

from twisted.web.client import Agent, FileBodyProducer, Headers, ResponseDone
from twisted.internet import threads, defer, protocol
from Crypto.Hash import SHA
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_PSS
from StringIO import StringIO
import time
import json
import binascii


class BeginningPrinter(protocol.Protocol):
    def __init__(self, finished):
        self.finished = finished
        self.data = ""

    def dataReceived(self, bytes):
        self.data = self.data + bytes

    def connectionLost(self, reason):
        if reason.check(ResponseDone) is not None:
            self.finished.callback(str(self.data))
        else:
            self.finished.errback(reason)


def read_body(response):
    d = defer.Deferred()
    response.deliverBody(BeginningPrinter(d))
    return d


def get_body(response):
    if response.code != 200:
        print "\n\n\n\nbad error code\n\n\n\n"
        raise ValueError(response.phrase)
    else:
        return read_body(response)


def get_body_from_request(path, data):

    from twisted.internet import reactor

    jsondata = FileBodyProducer(StringIO(json.dumps(data)))
    agent = Agent(reactor)
    d = agent.request(
        'POST', conf.settings['pointtrader_server'] + path,
        Headers({'Content-Type': ['application/json']}), jsondata)
    d.addCallback(get_body)
    return d


def print_response(response):
    pass


def print_error(err):
    print err.getTraceback()
    return err


def register_new_account(private_key):
    data = {}
    data['pub_key'] = private_key.publickey().exportKey()

    def get_success_from_body(body):
        r = json.loads(body)
        if not 'success' in r or r['success'] is False:
            return False
        return True

    d = get_body_from_request('/register/', data)

    d.addCallback(get_success_from_body)
    return d


def send_points(private_key, recipient_public_key, amount):
    encoded_public_key = private_key.publickey().exportKey()
    timestamp = time.time()
    h = SHA.new()
    h.update(encoded_public_key)
    h.update(recipient_public_key)
    h.update(str(amount))
    h.update(str(timestamp))
    signer = PKCS1_PSS.new(private_key)
    signature = binascii.hexlify(signer.sign(h))

    data = {}
    data['sender_pub_key'] = encoded_public_key
    data['recipient_pub_key'] = recipient_public_key
    data['amount'] = amount
    data['timestamp'] = timestamp
    data['signature'] = signature

    def get_success_from_body(body):
        r = json.loads(body)
        if not 'success' in r or r['success'] is False:
            return False
        return True

    d = get_body_from_request('/send-points/', data)

    d.addCallback(get_success_from_body)

    return d


def get_recent_transactions(private_key):
    encoded_public_key = private_key.publickey().exportKey()
    timestamp = time.time()
    h = SHA.new()
    h.update(encoded_public_key)
    h.update(str(timestamp))
    signer = PKCS1_PSS.new(private_key)
    signature = binascii.hexlify(signer.sign(h))

    data = {}
    data['pub_key'] = encoded_public_key
    data['timestamp'] = timestamp
    data['signature'] = signature
    data['end_time'] = 0
    data['start_time'] = 120

    def get_transactions_from_body(body):
        r = json.loads(body)
        if "transactions" not in r:
            raise ValueError("Invalid response: no 'transactions' field")
        else:
            return r['transactions']

    d = get_body_from_request('/get-transactions/', data)

    d.addCallback(get_transactions_from_body)

    return d


def get_balance(private_key):
    encoded_public_key = private_key.publickey().exportKey()
    timestamp = time.time()
    h = SHA.new()
    h.update(encoded_public_key)
    h.update(str(timestamp))
    signer = PKCS1_PSS.new(private_key)
    signature = binascii.hexlify(signer.sign(h))

    data = {}
    data['pub_key'] = encoded_public_key
    data['timestamp'] = timestamp
    data['signature'] = signature

    def get_balance_from_body(body):
        r = json.loads(body)
        if not 'balance' in r:
            raise ValueError("Invalid response: no 'balance' field")
        else:
            return float(r['balance'])

    d = get_body_from_request('/get-balance/', data)

    d.addCallback(get_balance_from_body)

    return d


def run_full_test():

    keys = []

    def save_key(private_key):
        keys.append(private_key)
        return private_key

    def check_balances_and_transactions(unused, bal1, bal2, num_transactions):

        def assert_balance_is(actual, expected):
            assert abs(actual - expected) < .05
            print "correct balance. actual:", str(actual), "expected:", str(expected)
            return True

        def assert_transaction_length_is(transactions, expected_length):
            assert len(transactions) == expected_length
            print "correct transaction length"
            return True

        d1 = get_balance(keys[0])
        d1.addCallback(assert_balance_is, bal1)

        d2 = get_balance(keys[1])
        d2.addCallback(assert_balance_is, bal2)

        d3 = get_recent_transactions(keys[0])
        d3.addCallback(assert_transaction_length_is, num_transactions)

        d4 = get_recent_transactions(keys[1])
        d4.addCallback(assert_transaction_length_is, num_transactions)

        dl = defer.DeferredList([d1, d2, d3, d4])
        return dl

    def do_transfer(unused, amount):
        d = send_points(keys[0], keys[1].publickey().exportKey(), amount)
        return d

    d1 = threads.deferToThread(RSA.generate, 4096)
    d1.addCallback(save_key)
    d1.addCallback(register_new_account)
    d2 = threads.deferToThread(RSA.generate, 4096)
    d2.addCallback(save_key)
    d2.addCallback(register_new_account)
    dlist = defer.DeferredList([d1, d2])
    dlist.addCallback(check_balances_and_transactions, 1000, 1000, 0)
    dlist.addCallback(do_transfer, 50)
    dlist.addCallback(check_balances_and_transactions, 950, 1050, 1)
    dlist.addCallback(do_transfer, 75)
    dlist.addCallback(check_balances_and_transactions, 875, 1125, 2)
    dlist.addErrback(print_error)


if __name__ == "__main__":

    from twisted.internet import reactor

    reactor.callLater(1, run_full_test)
    reactor.callLater(25, reactor.stop)
    reactor.run()
