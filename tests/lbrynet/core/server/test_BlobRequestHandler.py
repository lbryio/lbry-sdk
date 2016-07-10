import mock
from twisted.internet import defer
from twisted.trial import unittest

from lbrynet.core.server import BlobRequestHandler


class TestBlobRequestHandlerQueries(unittest.TestCase):
    def setUp(self):
        self.blob_manager = mock.Mock()
        self.payment_rate_manager = mock.Mock()
        self.handler = BlobRequestHandler.BlobRequestHandler(
            self.blob_manager, None, self.payment_rate_manager)

    def test_empty_response_when_empty_query(self):
        self.assertEqual({}, self.successResultOf(self.handler.handle_queries({})))
        
    def test_error_set_when_rate_is_missing(self):
        query = {'requested_blob': 'blob'}
        deferred = self.handler.handle_queries(query)
        response = {'incoming_blob': {'error': 'RATE_UNSET'}}
        self.assertEqual(response, self.successResultOf(deferred))

    def test_error_set_when_rate_too_low(self):
        self.payment_rate_manager.accept_rate_blob_data.return_value = False
        query = {
            'blob_data_payment_rate': 'way_too_low',
            'requested_blob': 'blob'
        }
        deferred = self.handler.handle_queries(query)
        response = {
            'blob_data_payment_rate': 'RATE_TOO_LOW',
            'incoming_blob': {'error': 'RATE_UNSET'}
        }
        self.assertEqual(response, self.successResultOf(deferred))

    def test_response_when_rate_too_low(self):
        self.payment_rate_manager.accept_rate_blob_data.return_value = False
        query = {
            'blob_data_payment_rate': 'way_too_low',
        }
        deferred = self.handler.handle_queries(query)
        response = {
            'blob_data_payment_rate': 'RATE_TOO_LOW',
        }
        self.assertEqual(response, self.successResultOf(deferred))

    def test_blob_unavailable_when_blob_not_validated(self):
        self.payment_rate_manager.accept_rate_blob_data.return_value = True
        blob = mock.Mock()
        blob.is_validated.return_value = False
        self.blob_manager.get_blob.return_value = defer.succeed(blob)
        query = {
            'blob_data_payment_rate': 'rate',
            'requested_blob': 'blob'
        }
        deferred = self.handler.handle_queries(query)
        response = {
            'blob_data_payment_rate': 'RATE_ACCEPTED',
            'incoming_blob': {'error': 'BLOB_UNAVAILABLE'}
        }
        self.assertEqual(response, self.successResultOf(deferred))

    def test_blob_unavailable_when_blob_cannot_be_opened(self):
        self.payment_rate_manager.accept_rate_blob_data.return_value = True
        blob = mock.Mock()
        blob.is_validated.return_value = True
        blob.open_for_reading.return_value = None
        self.blob_manager.get_blob.return_value = defer.succeed(blob)
        query = {
            'blob_data_payment_rate': 'rate',
            'requested_blob': 'blob'
        }
        deferred = self.handler.handle_queries(query)
        response = {
            'blob_data_payment_rate': 'RATE_ACCEPTED',
            'incoming_blob': {'error': 'BLOB_UNAVAILABLE'}
        }
        self.assertEqual(response, self.successResultOf(deferred))

    def test_blob_details_are_set_when_all_conditions_are_met(self):
        self.payment_rate_manager.accept_rate_blob_data.return_value = True
        blob = mock.Mock()
        blob.is_validated.return_value = True
        blob.open_for_reading.return_value = True
        blob.blob_hash = 'DEADBEEF'
        blob.length = 42
        self.blob_manager.get_blob.return_value = defer.succeed(blob)
        query = {
            'blob_data_payment_rate': 'rate',
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
        self.assertEqual(response, self.successResultOf(deferred))
        

        
