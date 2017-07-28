import logging
from collections import defaultdict
from decimal import Decimal

from twisted.internet import defer
from twisted.python.failure import Failure
from zope.interface import implements

from lbrynet.core.Error import ConnectionClosedBeforeResponseError
from lbrynet.core.Error import InvalidResponseError, RequestCanceledError, NoResponseError
from lbrynet.core.Error import PriceDisagreementError, DownloadCanceledError, InsufficientFundsError
from lbrynet.core.client.ClientRequest import ClientRequest, ClientBlobRequest
from lbrynet.interfaces import IRequestCreator
from lbrynet.core.Offer import Offer


log = logging.getLogger(__name__)


def get_points(num_bytes, rate):
    if isinstance(rate, float):
        return 1.0 * num_bytes * rate / 2**20
    elif isinstance(rate, Decimal):
        return 1.0 * num_bytes * float(rate) / 2**20
    else:
        raise Exception("Unknown rate type")


def cache(fn):
    """Caches the function call for each instance"""
    attr = '__{}_value'.format(fn.__name__)

    def helper(self):
        if not hasattr(self, attr):
            value = fn(self)
            setattr(self, attr, value)
        return getattr(self, attr)
    return helper


class BlobRequester(object):
    implements(IRequestCreator)

    def __init__(self, blob_manager, peer_finder, payment_rate_manager, wallet, download_manager):
        self.blob_manager = blob_manager
        self.peer_finder = peer_finder
        self.payment_rate_manager = payment_rate_manager
        self.wallet = wallet
        self._download_manager = download_manager
        self._peers = defaultdict(int)  # {Peer: score}
        self._available_blobs = defaultdict(list)  # {Peer: [blob_hash]}
        self._unavailable_blobs = defaultdict(list)  # {Peer: [blob_hash]}}
        self._protocol_prices = {}  # {ClientProtocol: price}
        self._protocol_offers = {}
        self._price_disagreements = []  # [Peer]
        self._protocol_tries = {}
        self._maxed_out_peers = []
        self._incompatible_peers = []

    ######## IRequestCreator #########
    def send_next_request(self, peer, protocol):
        """Makes an availability request, download request and price request"""
        if not self.should_send_next_request(peer):
            return defer.succeed(False)
        return self._send_next_request(peer, protocol)

    @defer.inlineCallbacks
    def get_new_peers_for_head_blob(self):
        """ look for peers for the head blob """
        head_blob_hash = self._download_manager.get_head_blob_hash()
        peers = yield self._find_peers_for_hash(head_blob_hash)
        defer.returnValue(peers)

    @defer.inlineCallbacks
    def get_new_peers_for_next_unavailable(self):
        """ look for peers for the next unavailable blob """
        blob_hash = yield self._get_hash_for_peer_search()
        peers = yield self._find_peers_for_hash(blob_hash)
        defer.returnValue(peers)

    ######### internal calls #########
    def should_send_next_request(self, peer):
        return (
            self._blobs_to_download() and
            self._should_send_request_to(peer)
        )

    def _send_next_request(self, peer, protocol):
        log.debug('Sending a blob request for %s and %s', peer, protocol)
        availability = AvailabilityRequest(self, peer, protocol, self.payment_rate_manager)
        head_blob_hash = self._download_manager.get_head_blob_hash()
        download = DownloadRequest(self, peer, protocol, self.payment_rate_manager,
                                   self.wallet, head_blob_hash)
        price = PriceRequest(self, peer, protocol, self.payment_rate_manager)

        sent_request = False
        if availability.can_make_request():
            availability.make_request_and_handle_response()
            sent_request = True
        if price.can_make_request():
            # TODO: document why a PriceRequest is only made if an
            # Availability or Download request was made
            price.make_request_and_handle_response()
            sent_request = True
        if download.can_make_request():
            try:
                download.make_request_and_handle_response()
                sent_request = True
            except InsufficientFundsError as err:
                return defer.fail(err)

        return defer.succeed(sent_request)

    def _get_hash_for_peer_search(self):
        r = None
        blobs_to_download = self._blobs_to_download()
        if blobs_to_download:
            blobs_without_sources = self._blobs_without_sources()
            if not blobs_without_sources:
                blob_hash = blobs_to_download[0].blob_hash
            else:
                blob_hash = blobs_without_sources[0].blob_hash
            r = blob_hash
        log.debug("Blob requester peer search response: %s", str(r))
        return defer.succeed(r)

    def _find_peers_for_hash(self, h):
        if h is None:
            return None
        else:
            d = self.peer_finder.find_peers_for_blob(h)

            def choose_best_peers(peers):
                bad_peers = self._get_bad_peers()
                without_bad_peers = [p for p in peers if not p in bad_peers]
                without_maxed_out_peers = [
                    p for p in without_bad_peers if p not in self._maxed_out_peers]
                return without_maxed_out_peers

            d.addCallback(choose_best_peers)

            def lookup_failed(err):
                log.error("An error occurred looking up peers for a hash: %s", err.getTraceback())
                return []

            d.addErrback(lookup_failed)
            return d

    def _should_send_request_to(self, peer):
        if self._peers[peer] < -5.0:
            return False
        if peer in self._price_disagreements:
            return False
        if peer in self._incompatible_peers:
            return False
        return True

    def _get_bad_peers(self):
        return [p for p in self._peers.iterkeys() if not self._should_send_request_to(p)]

    def _hash_available(self, blob_hash):
        for peer in self._available_blobs:
            if blob_hash in self._available_blobs[peer]:
                return True
        return False

    def _hash_available_on(self, blob_hash, peer):
        if blob_hash in self._available_blobs[peer]:
            return True
        return False

    def _blobs_to_download(self):
        needed_blobs = self._download_manager.needed_blobs()
        return sorted(needed_blobs, key=lambda b: b.is_downloading())

    def _blobs_without_sources(self):
        return [
            b for b in self._download_manager.needed_blobs()
            if not self._hash_available(b.blob_hash)
        ]

    def _price_settled(self, protocol):
        if protocol in self._protocol_prices:
            return True
        return False

    def _update_local_score(self, peer, amount):
        self._peers[peer] += amount


class RequestHelper(object):
    def __init__(self, requestor, peer, protocol, payment_rate_manager):
        self.requestor = requestor
        self.peer = peer
        self.protocol = protocol
        self.payment_rate_manager = payment_rate_manager

    @property
    def protocol_prices(self):
        return self.requestor._protocol_prices

    @property
    def protocol_offers(self):
        return self.requestor._protocol_offers

    @property
    def available_blobs(self):
        return self.requestor._available_blobs[self.peer]

    @property
    def unavailable_blobs(self):
        return self.requestor._unavailable_blobs[self.peer]

    @property
    def maxed_out_peers(self):
        return self.requestor._maxed_out_peers

    def update_local_score(self, score):
        self.requestor._update_local_score(self.peer, score)

    def _request_failed(self, reason, request_type):
        if reason.check(RequestCanceledError):
            return
        if reason.check(NoResponseError):
            self.requestor._incompatible_peers.append(self.peer)
        log.warning("A request of type '%s' failed. Reason: %s, Error type: %s",
                    request_type, reason.getErrorMessage(), reason.type)
        self.update_local_score(-10.0)
        if isinstance(reason, (InvalidResponseError, NoResponseError)):
            self.peer.update_score(-10.0)
        else:
            self.peer.update_score(-2.0)
        if reason.check(ConnectionClosedBeforeResponseError):
            return
        return reason

    def get_rate(self):
        if self.payment_rate_manager.price_limit_reached(self.peer):
            if self.peer not in self.maxed_out_peers:
                self.maxed_out_peers.append(self.peer)
            return None
        rate = self.protocol_prices.get(self.protocol)
        if rate is None:
            if self.peer in self.payment_rate_manager.strategy.pending_sent_offers:
                pending = self.payment_rate_manager.strategy.pending_sent_offers[self.peer]
                if not pending.is_too_low and not pending.is_accepted:
                    return pending.rate
            rate = self.payment_rate_manager.get_rate_blob_data(self.peer, self.available_blobs)
        return rate


def _handle_incoming_blob(response_dict, peer, request):
    if request.response_identifier not in response_dict:
        return InvalidResponseError("response identifier not in response")
    if not isinstance(response_dict[request.response_identifier], dict):
        return InvalidResponseError("response not a dict. got %s" %
                                    type(response_dict[request.response_identifier]))
    response = response_dict[request.response_identifier]
    if 'error' in response:
        # This means we're not getting our blob for some reason
        if response['error'] == "RATE_UNSET":
            # Stop the download with an error that won't penalize the peer
            request.cancel(PriceDisagreementError())
        else:
            # The peer has done something bad so we should get out of here
            return InvalidResponseError("Got an unknown error from the peer: %s" %
                                        (response['error'],))
    else:
        if 'blob_hash' not in response:
            return InvalidResponseError("Missing the required field 'blob_hash'")
        if not response['blob_hash'] == request.request_dict['requested_blob']:
            return InvalidResponseError(
                "Incoming blob does not match expected. Incoming: %s. Expected: %s" %
                (response['blob_hash'], request.request_dict['requested_blob'])
            )
        if 'length' not in response:
            return InvalidResponseError("Missing the required field 'length'")
        if not request.blob.set_length(response['length']):
            return InvalidResponseError("Could not set the length of the blob")
    return True


def _handle_download_error(err, peer, blob_to_download):
    if not err.check(DownloadCanceledError, PriceDisagreementError, RequestCanceledError):
        log.warning("An error occurred while downloading %s from %s. Error: %s",
                    blob_to_download.blob_hash, str(peer), err.getTraceback())
    if err.check(PriceDisagreementError):
        # Don't kill the whole connection just because a price couldn't be agreed upon.
        # Other information might be desired by other request creators at a better rate.
        return True
    return err


class AvailabilityRequest(RequestHelper):
    """Ask a peer what blobs it has available.

    Results are saved in `_available_blobs` and `_unavailable_blobs`
    on the parent BlobRequester.
    """
    def can_make_request(self):
        return self.get_top_needed_blobs()

    def make_request_and_handle_response(self):
        request = self._get_request()
        self._handle_request(request)

    def _get_request(self):
        to_request = self.get_top_needed_blobs()
        if not to_request:
            raise Exception('Unable to make a request without available blobs')
        return self._make_request(to_request)

    @cache
    def get_top_needed_blobs(self, limit=20):
        all_needed = [
            b.blob_hash for b in self.requestor._blobs_to_download()
            if not self.is_available(b)
        ]
        # sort them so that the peer will be asked first for blobs it
        # hasn't said it doesn't have
        sorted_needed = sorted(
            all_needed,
            key=lambda b: b in self.unavailable_blobs
        )
        return sorted_needed[:limit]

    def is_available(self, blob):
        return blob.blob_hash in self.available_blobs

    def _make_request(self, to_request):
        log.debug('Requesting blobs: %s', to_request)
        r_dict = {'requested_blobs': to_request}
        response_identifier = 'available_blobs'
        request = ClientRequest(r_dict, response_identifier)
        return request

    def _handle_request(self, a_r):
        log.debug('making an availability request')
        d1 = self.protocol.add_request(a_r)
        d1.addCallback(self._handle_availability, a_r)
        d1.addErrback(self._request_failed, "availability request")

    def _handle_availability(self, response_dict, request):
        assert request.response_identifier == 'available_blobs'
        if 'available_blobs' not in response_dict:
            raise InvalidResponseError("response identifier not in response")
        log.debug("Received a response to the availability request")
        # save available blobs
        blob_hashes = response_dict['available_blobs']
        for blob_hash in blob_hashes:
            if blob_hash in request.request_dict['requested_blobs']:
                self.process_available_blob_hash(blob_hash, request)
        # everything left in the request is missing
        for blob_hash in request.request_dict['requested_blobs']:
            self.unavailable_blobs.append(blob_hash)
        return True

    def process_available_blob_hash(self, blob_hash, request):
        log.debug("The server has indicated it has the following blob available: %s", blob_hash)
        self.available_blobs.append(blob_hash)
        self.remove_from_unavailable_blobs(blob_hash)
        request.request_dict['requested_blobs'].remove(blob_hash)

    def remove_from_unavailable_blobs(self, blob_hash):
        if blob_hash in self.unavailable_blobs:
            self.unavailable_blobs.remove(blob_hash)


class PriceRequest(RequestHelper):
    """Ask a peer if a certain price is acceptable"""
    def can_make_request(self):
        if len(self.available_blobs) and self.protocol not in self.protocol_prices:
            return self.get_rate() is not None
        return False

    def make_request_and_handle_response(self):
        request = self._get_price_request()
        self._handle_price_request(request)

    def _get_price_request(self):
        rate = self.get_rate()
        if rate is None:
            log.debug("No blobs to request from %s", self.peer)
            raise Exception('Cannot make a price request without a payment rate')
        log.debug("Offer rate %s to %s for %i blobs", rate, self.peer, len(self.available_blobs))

        request_dict = {'blob_data_payment_rate': rate}
        assert self.protocol not in self.protocol_offers
        self.protocol_offers[self.protocol] = rate
        return ClientRequest(request_dict, 'blob_data_payment_rate')

    def _handle_price_request(self, price_request):
        d = self.protocol.add_request(price_request)
        d.addCallback(self._handle_price_response, price_request)
        d.addErrback(self._request_failed, "price request")

    def _handle_price_response(self, response_dict, request):
        assert request.response_identifier == 'blob_data_payment_rate'
        if 'blob_data_payment_rate' not in response_dict:
            return InvalidResponseError("response identifier not in response")
        offer_value = self.protocol_offers.pop(self.protocol)
        offer = Offer(offer_value)
        offer.handle(response_dict['blob_data_payment_rate'])
        self.payment_rate_manager.record_offer_reply(self.peer, offer)
        if offer.is_accepted:
            log.info("Offered rate %f/mb accepted by %s", offer.rate, self.peer.host)
            self.protocol_prices[self.protocol] = offer.rate
            return True
        elif offer.is_too_low:
            log.debug("Offered rate %f/mb rejected by %s", offer.rate, self.peer.host)
            return not self.payment_rate_manager.price_limit_reached(self.peer)
        else:
            log.warning("Price disagreement")
            self.requestor._price_disagreements.append(self.peer)
            return False


class DownloadRequest(RequestHelper):
    """Choose a blob and download it from a peer and also pay the peer for the data."""
    def __init__(self, requester, peer, protocol, payment_rate_manager, wallet, head_blob_hash):
        RequestHelper.__init__(self, requester, peer, protocol, payment_rate_manager)
        self.wallet = wallet
        self.head_blob_hash = head_blob_hash

    def can_make_request(self):
        if self.protocol in self.protocol_prices:
            return self.get_blob_details()
        return False

    def make_request_and_handle_response(self):
        request = self._get_request()
        self._handle_download_request(request)

    def _get_request(self):
        blob_details = self.get_blob_details()
        if not blob_details:
            raise Exception('No blobs available to download')
        return self._make_request(blob_details)

    @cache
    def get_blob_details(self):
        """Open a blob for writing and return the details.

        If no blob can be opened, returns None.
        """
        to_download = self.get_available_blobs()
        return self.find_blob(to_download)

    def get_available_blobs(self):
        available_blobs = [
            b for b in self.requestor._blobs_to_download()
            if self.requestor._hash_available_on(b.blob_hash, self.peer)
        ]
        log.debug('available blobs: %s', available_blobs)
        return available_blobs

    def find_blob(self, to_download):
        """Return the first blob in `to_download` that is successfully opened for write."""
        for blob in to_download:
            if blob.is_validated():
                log.debug('Skipping blob %s as its already validated', blob)
                continue
            d, write_func, cancel_func = blob.open_for_writing(self.peer)
            if d is not None:
                return BlobDownloadDetails(blob, d, write_func, cancel_func, self.peer)
            log.debug('Skipping blob %s as there was an issue opening it for writing', blob)
        return None

    def _make_request(self, blob_details):
        blob = blob_details.blob
        request = ClientBlobRequest(
            {'requested_blob': blob.blob_hash},
            'incoming_blob',
            blob_details.counting_write_func,
            blob_details.deferred,
            blob_details.cancel_func,
            blob
        )
        log.debug("Requesting blob %s from %s", blob.blob_hash, self.peer)
        return request

    def _handle_download_request(self, client_blob_request):
        reserved_points = self.reserve_funds_or_cancel(client_blob_request)
        self.add_callbacks_to_download_request(client_blob_request, reserved_points)
        self.create_add_blob_request(client_blob_request)

    def reserve_funds_or_cancel(self, client_blob_request):
        reserved_points = self._reserve_points(client_blob_request.max_pay_units)
        if reserved_points is not None:
            return reserved_points
        client_blob_request.cancel(InsufficientFundsError())
        client_blob_request.finished_deferred.addErrback(lambda _: True)
        raise InsufficientFundsError()

    def add_callbacks_to_download_request(self, client_blob_request, reserved_points):
        # Note: The following three callbacks will be called when the blob has been
        # fully downloaded or canceled
        client_blob_request.finished_deferred.addCallbacks(
            self._download_succeeded,
            self._download_failed,
            callbackArgs=(client_blob_request.blob,),
        )
        client_blob_request.finished_deferred.addBoth(
            self._pay_or_cancel_payment, reserved_points, client_blob_request.blob)
        client_blob_request.finished_deferred.addErrback(
            _handle_download_error, self.peer, client_blob_request.blob)

    def _pay_or_cancel_payment(self, arg, reserved_points, blob):
        if self._can_pay_peer(blob, arg):
            self._pay_peer(blob.length, reserved_points)
            d = self.requestor.blob_manager.add_blob_to_download_history(
                str(blob), str(self.peer.host), float(self.protocol_prices[self.protocol]))
        else:
            self._cancel_points(reserved_points)
        return arg

    def _can_pay_peer(self, blob, arg):
        return (
            blob.length != 0 and
            (not isinstance(arg, Failure) or arg.check(DownloadCanceledError))
        )

    def _pay_peer(self, num_bytes, reserved_points):
        assert num_bytes != 0
        rate = self.get_rate()
        point_amount = get_points(num_bytes, rate)
        self.wallet.send_points(reserved_points, point_amount)
        self.payment_rate_manager.record_points_paid(point_amount)

    def _cancel_points(self, reserved_points):
        self.wallet.cancel_point_reservation(reserved_points)

    def create_add_blob_request(self, client_blob_request):
        d = self.protocol.add_blob_request(client_blob_request)
        # Note: The following two callbacks will be called as soon as the peer sends its
        # response, which will be before the blob has finished downloading, but may be
        # after the blob has been canceled. For example,
        # 1) client sends request to Peer A
        # 2) the blob is finished downloading from peer B, and therefore this one is canceled
        # 3) client receives response from Peer A
        # Therefore, these callbacks shouldn't rely on there being a blob about to be
        # downloaded.
        d.addCallback(_handle_incoming_blob, self.peer, client_blob_request)
        d.addErrback(self._request_failed, "download request")

    def _reserve_points(self, num_bytes):
        # jobevers: there was an assertion here, but I don't think it
        # was a valid assertion to make. It is possible for a rate to
        # not yet been set for this protocol or for it to have been
        # removed so instead I switched it to check if a rate has been set
        # and calculate it if it has not
        rate = self.get_rate()
        points_to_reserve = get_points(num_bytes, rate)
        return self.wallet.reserve_points(self.peer, points_to_reserve)

    def _download_succeeded(self, arg, blob):
        log.info("Blob %s has been successfully downloaded from %s", blob, self.peer)
        self.update_local_score(5.0)
        self.peer.update_stats('blobs_downloaded', 1)
        self.peer.update_score(5.0)
        should_announce = blob.blob_hash == self.head_blob_hash
        self.requestor.blob_manager.blob_completed(blob, should_announce=should_announce)
        return arg

    def _download_failed(self, reason):
        if not reason.check(DownloadCanceledError, PriceDisagreementError):
            self.update_local_score(-10.0)
        return reason


class BlobDownloadDetails(object):
    """Contains the information needed to make a ClientBlobRequest from an open blob"""
    def __init__(self, blob, deferred, write_func, cancel_func, peer):
        self.blob = blob
        self.deferred = deferred
        self.write_func = write_func
        self.cancel_func = cancel_func
        self.peer = peer

    def counting_write_func(self, data):
        self.peer.update_stats('blob_bytes_downloaded', len(data))
        return self.write_func(data)
