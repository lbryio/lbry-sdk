import StringIO

import mock
from twisted.internet import defer
from twisted.test import proto_helpers
from twisted.trial import unittest

from lbrynet import analytics
from lbrynet.core import Peer
from lbrynet.core.server import BlobRequestHandler
from lbrynet.core.PaymentRateManager import NegotiatedPaymentRateManager, BasePaymentRateManager
from tests.mocks import BlobAvailabilityTracker as DummyBlobAvailabilityTracker, mock_conf_settings


class TestBlobRequestHandlerQueries(unittest.TestCase):
    def setUp(self):
        mock_conf_settings(self)
        self.blob_manager = mock.Mock()
        self.payment_rate_manager = NegotiatedPaymentRateManager(
            BasePaymentRateManager(0.001), DummyBlobAvailabilityTracker())
        self.handler = BlobRequestHandler.BlobRequestHandler(
            self.blob_manager, None, self.payment_rate_manager, None)

    def test_empty_response_when_empty_query(self):
        self.assertEqual({}, self.successResultOf(self.handler.handle_queries({})))

    def test_error_set_when_rate_is_missing(self):
        query = {'requested_blob': 'blob'}
        deferred = self.handler.handle_queries(query)
        response = {'incoming_blob': {'error': 'RATE_UNSET'}}
        self.assertEqual(response, self.successResultOf(deferred))

    def test_error_set_when_rate_too_low(self):
        query = {
            'blob_data_payment_rate': '-1.0',
            'requested_blob': 'blob'
        }
        deferred = self.handler.handle_queries(query)
        response = {
            'blob_data_payment_rate': 'RATE_TOO_LOW',
            'incoming_blob': {'error': 'RATE_UNSET'}
        }
        self.assertEqual(response, self.successResultOf(deferred))

    def test_response_when_rate_too_low(self):
        query = {
            'blob_data_payment_rate': '-1.0',
        }
        deferred = self.handler.handle_queries(query)
        response = {
            'blob_data_payment_rate': 'RATE_TOO_LOW',
        }
        self.assertEqual(response, self.successResultOf(deferred))

    def test_blob_unavailable_when_blob_not_validated(self):
        blob = mock.Mock()
        blob.is_validated.return_value = False
        self.blob_manager.get_blob.return_value = defer.succeed(blob)
        query = {
            'blob_data_payment_rate': 1.0,
            'requested_blob': 'blob'
        }
        deferred = self.handler.handle_queries(query)
        response = {
            'blob_data_payment_rate': 'RATE_ACCEPTED',
            'incoming_blob': {'error': 'BLOB_UNAVAILABLE'}
        }
        self.assertEqual(response, self.successResultOf(deferred))

    def test_blob_unavailable_when_blob_cannot_be_opened(self):
        blob = mock.Mock()
        blob.is_validated.return_value = True
        blob.open_for_reading.return_value = None
        self.blob_manager.get_blob.return_value = defer.succeed(blob)
        query = {
            'blob_data_payment_rate': 0.0,
            'requested_blob': 'blob'
        }
        deferred = self.handler.handle_queries(query)
        response = {
            'blob_data_payment_rate': 'RATE_ACCEPTED',
            'incoming_blob': {'error': 'BLOB_UNAVAILABLE'}
        }
        self.assertEqual(response, self.successResultOf(deferred))

    def test_blob_details_are_set_when_all_conditions_are_met(self):
        blob = mock.Mock()
        blob.is_validated.return_value = True
        blob.open_for_reading.return_value = True
        blob.blob_hash = 'DEADBEEF'
        blob.length = 42
        peer = mock.Mock()
        peer.host = "1.2.3.4"
        self.handler.peer = peer
        self.blob_manager.get_blob.return_value = defer.succeed(blob)
        query = {
            'blob_data_payment_rate': 1.0,
            'requested_blob': 'blob'
        }
        deferred = self.handler.handle_queries(query)
        response = {
            'blob_data_payment_rate': 'RATE_ACCEPTED',
            'incoming_blob': {
                'blob_hash': 'DEADBEEF',
                'length': 42
            }
        }
        result = self.successResultOf(deferred)
        self.assertEqual(response, result)


class TestBlobRequestHandlerSender(unittest.TestCase):
    def test_nothing_happens_if_not_currently_uploading(self):
        handler = BlobRequestHandler.BlobRequestHandler(None, None, None, None)
        handler.currently_uploading = None
        deferred = handler.send_blob_if_requested(None)
        self.assertEqual(True, self.successResultOf(deferred))

    def test_file_is_sent_to_consumer(self):
        # TODO: also check that the expected payment values are set
        consumer = proto_helpers.StringTransport()
        test_file = StringIO.StringIO('test')
        track = analytics.Track()
        handler = BlobRequestHandler.BlobRequestHandler(None, None, None, track)
        handler.peer = mock.create_autospec(Peer.Peer)
        handler.currently_uploading = mock.Mock()
        handler.read_handle = test_file
        handler.send_blob_if_requested(consumer)
        while consumer.producer:
            consumer.producer.resumeProducing()
        self.assertEqual(consumer.value(), 'test')
