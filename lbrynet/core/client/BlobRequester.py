import logging
from collections import defaultdict

from twisted.internet import defer
from twisted.python.failure import Failure
from zope.interface import implements

from lbrynet.core.Error import ConnectionClosedBeforeResponseError
from lbrynet.core.Error import InvalidResponseError, RequestCanceledError, NoResponseError
from lbrynet.core.Error import PriceDisagreementError, DownloadCanceledError, InsufficientFundsError
from lbrynet.core.client.ClientRequest import ClientRequest, ClientBlobRequest
from lbrynet.interfaces import IRequestCreator
from lbrynet.core.Offer import Negotiate, Offer

log = logging.getLogger(__name__)


class BlobRequester(object):
    implements(IRequestCreator)

    def __init__(self, blob_manager, peer_finder, payment_rate_manager, wallet, download_manager):
        self.blob_manager = blob_manager
        self.peer_finder = peer_finder
        self.payment_rate_manager = payment_rate_manager
        self.wallet = wallet
        self.download_manager = download_manager
        self._peers = defaultdict(int)  # {Peer: score}
        self._available_blobs = defaultdict(list)  # {Peer: [blob_hash]}
        self._unavailable_blobs = defaultdict(list)  # {Peer: [blob_hash]}}
        self._protocol_prices = {}  # {ClientProtocol: price}
        self._price_disagreements = []  # [Peer]
        self._protocol_tries = {}
        self._incompatible_peers = []

    ######## IRequestCreator #########

    def send_next_request(self, peer, protocol):
        sent_request = False
        if self._blobs_to_download() and self._should_send_request_to(peer):
            a_r = self._get_availability_request(peer)
            d_r = self._get_download_request(peer)
            p_r = None

            if a_r is not None or d_r is not None:
                p_r = self._get_price_request(peer, protocol)

            if a_r is not None:
                d1 = protocol.add_request(a_r)
                d1.addCallback(self._handle_availability, peer, a_r)
                d1.addErrback(self._request_failed, "availability request", peer)
                sent_request = True

            if d_r is not None and protocol in self._protocol_prices:
                reserved_points = self._reserve_points(peer, protocol, d_r.max_pay_units)
                if reserved_points is not None:
                    # Note: The following three callbacks will be called when the blob has been
                    # fully downloaded or canceled
                    d_r.finished_deferred.addCallbacks(self._download_succeeded, self._download_failed,
                                                       callbackArgs=(peer, d_r.blob),
                                                       errbackArgs=(peer,))
                    d_r.finished_deferred.addBoth(self._pay_or_cancel_payment, protocol, reserved_points, d_r.blob)
                    d_r.finished_deferred.addErrback(self._handle_download_error, peer, d_r.blob)

                    d2 = protocol.add_blob_request(d_r)
                    # Note: The following two callbacks will be called as soon as the peer sends its
                    # response, which will be before the blob has finished downloading, but may be
                    # after the blob has been canceled. For example,
                    # 1) client sends request to Peer A
                    # 2) the blob is finished downloading from peer B, and therefore this one is canceled
                    # 3) client receives response from Peer A
                    # Therefore, these callbacks shouldn't rely on there being a blob about to be
                    # downloaded.
                    d2.addCallback(self._handle_incoming_blob, peer, d_r)
                    d2.addErrback(self._request_failed, "download request", peer)
                    sent_request = True
                else:
                    d_r.cancel(InsufficientFundsError())
                    d_r.finished_deferred.addErrback(lambda _: True)
                    return defer.fail(InsufficientFundsError())

            if sent_request is True:
                if p_r is not None:
                    d3 = protocol.add_request(p_r)
                    d3.addCallback(self._handle_price_response, peer, p_r, protocol)
                    d3.addErrback(self._request_failed, "price request", peer)

        return defer.succeed(sent_request)

    def get_new_peers(self):
        d = self._get_hash_for_peer_search()
        d.addCallback(self._find_peers_for_hash)
        return d

    ######### internal calls #########

    def _blobs_to_download(self):
        needed_blobs = self.download_manager.needed_blobs()
        return sorted(needed_blobs, key=lambda b: b.is_downloading())

    def _get_blobs_to_request_from_peer(self, peer):
        all_needed = [b.blob_hash for b in self._blobs_to_download() if not b.blob_hash in self._available_blobs[peer]]
        # sort them so that the peer will be asked first for blobs it hasn't said it doesn't have
        to_request = sorted(all_needed, key=lambda b: b in self._unavailable_blobs[peer])[:20]
        return to_request

    def _price_settled(self, protocol):
        if protocol in self._protocol_prices:
            return True
        return False

    def _get_price_request(self, peer, protocol):
        request = None
        response_identifier = Negotiate.PAYMENT_RATE
        if protocol not in self._protocol_prices:
            blobs_to_request = self._available_blobs[peer]
            if blobs_to_request:
                rate = self.payment_rate_manager.get_rate_blob_data(peer, blobs_to_request)
                self._protocol_prices[protocol] = rate
                offer = Offer(rate)
                request = ClientRequest(Negotiate.make_dict_from_offer(offer), response_identifier)
                log.debug("Offer rate %s to %s for %i blobs",  str(rate), str(peer), len(blobs_to_request))
            else:
                log.debug("No blobs to request from %s", str(peer))
        return request

    def _handle_price_response(self, response_dict, peer, request, protocol):
        if not request.response_identifier in response_dict:
            return InvalidResponseError("response identifier not in response")
        assert protocol in self._protocol_prices
        offer = Negotiate.get_offer_from_request(response_dict)
        rate = self._protocol_prices[protocol]
        if offer.accepted:
            log.info("Offered rate %f/mb accepted by %s", rate, str(peer.host))
            return True
        elif offer.too_low:
            log.info("Offered rate %f/mb rejected by %s", rate, str(peer.host))
            del self._protocol_prices[protocol]
            return True
        else:
            log.warning("Price disagreement")
            log.warning(offer.rate)
            del self._protocol_prices[protocol]
            self._price_disagreements.append(peer)
            return False

    def _download_succeeded(self, arg, peer, blob):
        log.info("Blob %s has been successfully downloaded from %s", str(blob), str(peer))
        self._update_local_score(peer, 5.0)
        peer.update_stats('blobs_downloaded', 1)
        peer.update_score(5.0)
        self.blob_manager.blob_completed(blob)
        return arg

    def _download_failed(self, reason, peer):
        if not reason.check(DownloadCanceledError, PriceDisagreementError):
            self._update_local_score(peer, -10.0)
        return reason

    def _record_blob_acquired(self, blob, host, rate):
        d = self.blob_manager.add_blob_to_download_history(blob, host, rate)

    def _pay_or_cancel_payment(self, arg, protocol, reserved_points, blob):
        if blob.length != 0 and (not isinstance(arg, Failure) or arg.check(DownloadCanceledError)):
            self._pay_peer(protocol, blob.length, reserved_points)
            self._record_blob_acquired(str(blob), protocol.peer.host, reserved_points.amount)
        else:
            self._cancel_points(reserved_points)

        return arg

    def _handle_download_error(self, err, peer, blob_to_download):
        if not err.check(DownloadCanceledError, PriceDisagreementError, RequestCanceledError):
            log.warning("An error occurred while downloading %s from %s. Error: %s",
                        blob_to_download.blob_hash, str(peer), err.getTraceback())
        if err.check(PriceDisagreementError):
            # Don't kill the whole connection just because a price couldn't be agreed upon.
            # Other information might be desired by other request creators at a better rate.
            return True
        return err

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
                return [p for p in peers if not p in bad_peers]

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

    def _blobs_without_sources(self):
        return [b for b in self.download_manager.needed_blobs() if not self._hash_available(b.blob_hash)]

    def _get_availability_request(self, peer):
        to_request = self._get_blobs_to_request_from_peer(peer)
        if to_request:
            r_dict = {'requested_blobs': to_request}
            response_identifier = 'available_blobs'
            request = ClientRequest(r_dict, response_identifier)
            return request
        return None

    def _get_download_request(self, peer):
        request = None
        to_download = [b for b in self._blobs_to_download() if self._hash_available_on(b.blob_hash, peer)]
        while to_download and request is None:
            blob_to_download = to_download[0]
            to_download = to_download[1:]
            if not blob_to_download.is_validated():
                d, write_func, cancel_func = blob_to_download.open_for_writing(peer)

                def counting_write_func(data):
                    peer.update_stats('blob_bytes_downloaded', len(data))
                    return write_func(data)

                if d is not None:

                    request_dict = {'requested_blob': blob_to_download.blob_hash}
                    response_identifier = 'incoming_blob'

                    request = ClientBlobRequest(request_dict, response_identifier, counting_write_func, d,
                                                cancel_func, blob_to_download)

                    # log.info("Requesting blob %s from %s", str(blob_to_download), str(peer))
        return request

    def _update_local_score(self, peer, amount):
            self._peers[peer] += amount

    def _reserve_points(self, peer, protocol, max_bytes):
        if protocol in self._protocol_prices:
            points_to_reserve = 1.0 * max_bytes * self._protocol_prices[protocol] / 2 ** 20
            return self.wallet.reserve_points(peer, points_to_reserve)
        return None

    def _pay_peer(self, protocol, num_bytes, reserved_points):
        if num_bytes != 0 and protocol in self._protocol_prices:
            point_amount = 1.0 * num_bytes * self._protocol_prices[protocol] / 2**20
            self.wallet.send_points(reserved_points, point_amount)
            self.payment_rate_manager.record_points_paid(point_amount)
            log.debug("Pay peer %s", str(point_amount))

    def _cancel_points(self, reserved_points):
        self.wallet.cancel_point_reservation(reserved_points)

    def _handle_availability(self, response_dict, peer, request):
        if not request.response_identifier in response_dict:
            raise InvalidResponseError("response identifier not in response")
        log.debug("Received a response to the availability request")
        blob_hashes = response_dict[request.response_identifier]
        for blob_hash in blob_hashes:
            if blob_hash in request.request_dict['requested_blobs']:
                log.debug("The server has indicated it has the following blob available: %s", blob_hash)
                self._available_blobs[peer].append(blob_hash)
                if blob_hash in self._unavailable_blobs[peer]:
                    self._unavailable_blobs[peer].remove(blob_hash)
                request.request_dict['requested_blobs'].remove(blob_hash)
        for blob_hash in request.request_dict['requested_blobs']:
            self._unavailable_blobs[peer].append(blob_hash)
        return True

    def _handle_incoming_blob(self, response_dict, peer, request):
        log.debug("Handling incoming blob: %s", str(response_dict))
        if not request.response_identifier in response_dict:
            return InvalidResponseError("response identifier not in response")
        if not type(response_dict[request.response_identifier]) == dict:
            return InvalidResponseError("response not a dict. got %s" %
                                        (type(response_dict[request.response_identifier]),))
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
            if not 'blob_hash' in response:
                return InvalidResponseError("Missing the required field 'blob_hash'")
            if not response['blob_hash'] == request.request_dict['requested_blob']:
                return InvalidResponseError("Incoming blob does not match expected. Incoming: %s. Expected: %s" %
                                            (response['blob_hash'], request.request_dict['requested_blob']))
            if not 'length' in response:
                return InvalidResponseError("Missing the required field 'length'")
            if not request.blob.set_length(response['length']):
                return InvalidResponseError("Could not set the length of the blob")
        return True

    def _request_failed(self, reason, request_type, peer):
        if reason.check(RequestCanceledError):
            return
        if reason.check(NoResponseError):
            self._incompatible_peers.append(peer)
        log.warning("Blob requester: a request of type '%s' failed. Reason: %s, Error type: %s",
                    str(request_type), reason.getErrorMessage(), reason.type)
        self._update_local_score(peer, -10.0)
        if isinstance(reason, InvalidResponseError) or isinstance(reason, NoResponseError):
            peer.update_score(-10.0)
        else:
            peer.update_score(-2.0)
        if reason.check(ConnectionClosedBeforeResponseError):
            return
        return reason