from zope.interface import implements
from lbrynet.interfaces import IMetadataHandler, IRequestCreator
from lbrynet.core.client.ClientRequest import ClientRequest, ClientPaidRequest
from lbrynet.core.Error import InsufficientFundsError, InvalidResponseError, RequestCanceledError
from lbrynet.core.Error import NoResponseError, ConnectionClosedBeforeResponseError
from ValuableBlobInfo import ValuableBlobInfo
import datetime
import logging
import random
from twisted.internet import defer
from twisted.python.failure import Failure
from collections import defaultdict


class BlindMetadataHandler(object):
    implements(IMetadataHandler, IRequestCreator)

    def __init__(self, info_manager, peers, peer_finder, approved_peers, payment_rate_manager, wallet,
                 download_manager):
        self.info_manager = info_manager
        self.payment_rate_manager = payment_rate_manager
        self.wallet = wallet
        self.download_manager = download_manager
        self._peers = peers  # {Peer: score}
        self.peer_finder = peer_finder
        self.approved_peers = approved_peers
        self._valuable_protocol_prices = {}
        self._info_protocol_prices = {}
        self._price_disagreements = []  # [Peer]
        self._incompatible_peers = []  # [Peer]
        self._last_blob_hashes_from_peers = {}  # {Peer: (blob_hash, expire_time)}
        self._valuable_hashes = {}  # {blob_hash: (peer score, reference, peer)}
        self._blob_infos = {}  # {blob_hash: ValuableBlobInfo}
        self._peer_search_results = defaultdict(list)  # {peer: [blob_hash]}

    ######### IMetadataHandler #########

    def get_initial_blobs(self):
        d = self.info_manager.get_all_blob_infos()
        return d

    def final_blob_num(self):
        return None

    ######### IRequestCreator #########

    def send_next_request(self, peer, protocol):
        # Basic idea:
        # If the peer has been sending us blob hashes to download recently (10 minutes?),
        # send back an example of one (the most recent?) so that it can
        # keep sending us more like it. Otherwise, just ask for
        # valuable blobs
        sent_request = False
        if self._should_send_request_to(peer):
            v_r = self._get_valuable_blob_request(peer)
            if v_r is not None:
                v_p_r = self._get_valuable_price_request(peer, protocol)
                reserved_points = self._reserve_points_valuable(peer, protocol, v_r.max_pay_units)
                if reserved_points is not None:
                    d1 = protocol.add_request(v_r)
                    d1.addCallback(self._handle_valuable_blob_response, peer, v_r)
                    d1.addBoth(self._pay_or_cancel_payment, protocol, reserved_points,
                               self._info_protocol_prices)
                    d1.addErrback(self._request_failed, "valuable blob request", peer)
                    sent_request = True
                    if v_p_r is not None:
                        d2 = protocol.add_request(v_p_r)
                        d2.addCallback(self._handle_valuable_price_response, peer, v_p_r, protocol)
                        d2.addErrback(self._request_failed, "valuable price request", peer)
                else:
                    return defer.fail(InsufficientFundsError())
            i_r = self._get_info_request(peer)
            if i_r is not None:
                i_p_r = self._get_info_price_request(peer, protocol)
                reserved_points = self._reserve_points_info(peer, protocol, i_r.max_pay_units)
                if reserved_points is not None:
                    d3 = protocol.add_request(i_r)
                    d3.addCallback(self._handle_info_response, peer, i_r, protocol, reserved_points)
                    d3.addBoth(self._pay_or_cancel_payment, protocol, reserved_points,
                               self._valuable_protocol_prices)
                    d3.addErrback(self._request_failed, "info request", peer, reserved_points)
                    sent_request = True
                    if i_p_r is not None:
                        d4 = protocol.add_request(i_p_r)
                        d4.addCallback(self._handle_info_price_response, peer, i_p_r, protocol)
                        d4.addErrback(self._request_failed, "info price request", peer)
                else:
                    return defer.fail(InsufficientFundsError())
        return defer.succeed(sent_request)

    def get_new_peers(self):
        peers = None
        if self._peer_search_results:
            peers = self._peer_search_results.keys()
        elif len(self.approved_peers) != 0:
            peers = random.sample(self.approved_peers, len(self.approved_peers))
        return defer.succeed(peers)

    ######### internal #########

    def _should_send_request_to(self, peer):
        if peer in self._incompatible_peers:
            return False
        if self._peers[peer] >= 0:
            return True
        return False

    def _get_valuable_blob_request(self, peer):
        blob_hash = None
        if peer in self._last_blob_hashes_from_peers:
            h, expire_time = self._last_blob_hashes_from_peers[peer]
            if datetime.datetime.now() > expire_time:
                del self._last_blob_hashes_from_peers[peer]
            else:
                blob_hash = h
        r_dict = {'valuable_blob_hashes': {'reference': blob_hash, 'max_blob_hashes': 20}}
        response_identifier = 'valuable_blob_hashes'
        request = ClientPaidRequest(r_dict, response_identifier, 20)
        return request

    def _get_valuable_price_request(self, peer, protocol):
        request = None
        if not protocol in self._valuable_protocol_prices:
            self._valuable_protocol_prices[protocol] = self.payment_rate_manager.get_rate_valuable_blob_hash(peer)
            request_dict = {'valuable_blob_payment_rate': self._valuable_protocol_prices[protocol]}
            request = ClientRequest(request_dict, 'valuable_blob_payment_rate')
        return request

    def _get_info_request(self, peer):
        if peer in self._peer_search_results:
            blob_hashes = self._peer_search_results[peer]
            del self._peer_search_results[peer]
            references = []
            for blob_hash in blob_hashes:
                if blob_hash in self._valuable_hashes:
                    references.append(self._valuable_hashes[blob_hash][1])
            hashes_to_search = [h for h, (s, r, p) in self._valuable_hashes.iteritems() if r in references]
            if hashes_to_search:
                r_dict = {'blob_length': {'blob_hashes': hashes_to_search}}
                response_identifier = 'blob_length'
                request = ClientPaidRequest(r_dict, response_identifier, len(hashes_to_search))
                return request
        if not self._peer_search_results:
            self._search_for_peers()
        return None

    def _get_info_price_request(self, peer, protocol):
        request = None
        if not protocol in self._info_protocol_prices:
            self._info_protocol_prices[protocol] = self.payment_rate_manager.get_rate_valuable_blob_info(peer)
            request_dict = {'blob_length_payment_rate': self._info_protocol_prices[protocol]}
            request = ClientRequest(request_dict, 'blob_length_payment_rate')
        return request

    def _update_local_score(self, peer, amount):
        self._peers[peer] += amount

    def _reserve_points_valuable(self, peer, protocol, max_units):
        return self._reserve_points(peer, protocol, max_units, self._valuable_protocol_prices)

    def _reserve_points_info(self, peer, protocol, max_units):
        return self._reserve_points(peer, protocol, max_units, self._info_protocol_prices)

    def _reserve_points(self, peer, protocol, max_units, prices):
        assert protocol in prices
        points_to_reserve = 1.0 * max_units * prices[protocol] / 1000.0
        return self.wallet.reserve_points(peer, points_to_reserve)

    def _pay_or_cancel_payment(self, arg, protocol, reserved_points, protocol_prices):
        if isinstance(arg, Failure) or arg == 0:
            self._cancel_points(reserved_points)
        else:
            self._pay_peer(protocol, arg, reserved_points, protocol_prices)
        return arg

    def _pay_peer(self, protocol, num_units, reserved_points, prices):
        assert num_units != 0
        assert protocol in prices
        point_amount = 1.0 * num_units * prices[protocol] / 1000.0
        self.wallet.send_points(reserved_points, point_amount)

    def _cancel_points(self, reserved_points):
        self.wallet.cancel_point_reservation(reserved_points)

    def _handle_valuable_blob_response(self, response_dict, peer, request):
        if not request.response_identifier in response_dict:
            return InvalidResponseError("response identifier not in response")
        response = response_dict[request.response_identifier]
        if 'error' in response:
            if response['error'] == "RATE_UNSET":
                return 0
            else:
                return InvalidResponseError("Got an unknown error from the peer: %s" %
                                            (response['error'],))
        if not 'valuable_blob_hashes' in response:
            return InvalidResponseError("Missing the required field 'valuable_blob_hashes'")
        hashes = response['valuable_blob_hashes']
        logging.info("Handling %s valuable blob hashes from %s", str(len(hashes)), str(peer))
        expire_time = datetime.datetime.now() + datetime.timedelta(minutes=10)
        reference = None
        unique_hashes = set()
        if 'reference' in response:
            reference = response['reference']
        for blob_hash, peer_score in hashes:
            if reference is None:
                reference = blob_hash
            self._last_blob_hashes_from_peers[peer] = (blob_hash, expire_time)
            if not (blob_hash in self._valuable_hashes or blob_hash in self._blob_infos):
                self._valuable_hashes[blob_hash] = (peer_score, reference, peer)
            unique_hashes.add(blob_hash)

        if len(unique_hashes):
            self._update_local_score(peer, len(unique_hashes))
            peer.update_stats('downloaded_valuable_blob_hashes', len(unique_hashes))
            peer.update_score(len(unique_hashes))
        else:
            self._update_local_score(peer, -.0001)
        return len(unique_hashes)

    def _handle_info_response(self, response_dict, peer, request):
        if not request.response_identifier in response_dict:
            return InvalidResponseError("response identifier not in response")
        response = response_dict[request.response_identifier]
        if 'error' in response:
            if response['error'] == 'RATE_UNSET':
                return 0
            else:
                return InvalidResponseError("Got an unknown error from the peer: %s" %
                                            (response['error'],))
        if not 'blob_lengths' in response:
            return InvalidResponseError("Missing the required field 'blob_lengths'")
        raw_blob_lengths = response['blob_lengths']
        logging.info("Handling %s blob lengths from %s", str(len(raw_blob_lengths)), str(peer))
        logging.debug("blobs: %s", str(raw_blob_lengths))
        infos = []
        unique_hashes = set()
        for blob_hash, length in raw_blob_lengths:
            if blob_hash in self._valuable_hashes:
                peer_score, reference, peer = self._valuable_hashes[blob_hash]
                del self._valuable_hashes[blob_hash]
                infos.append(ValuableBlobInfo(blob_hash, length, reference, peer, peer_score))
                unique_hashes.add(blob_hash)
            elif blob_hash in request.request_dict['blob_length']['blob_hashes']:
                unique_hashes.add(blob_hash)
        d = self.info_manager.save_blob_infos(infos)
        d.addCallback(lambda _: self.download_manager.add_blobs_to_download(infos))

        def pay_or_penalize_peer():
            if len(unique_hashes):
                self._update_local_score(peer, len(unique_hashes))
                peer.update_stats('downloaded_valuable_blob_infos', len(unique_hashes))
                peer.update_score(len(unique_hashes))
            else:
                self._update_local_score(peer, -.0001)
            return len(unique_hashes)

        d.addCallback(lambda _: pay_or_penalize_peer())

        return d

    def _handle_valuable_price_response(self, response_dict, peer, request, protocol):
        if not request.response_identifier in response_dict:
            return InvalidResponseError("response identifier not in response")
        assert protocol in self._valuable_protocol_prices
        response = response_dict[request.response_identifier]
        if response == "RATE_ACCEPTED":
            return True
        else:
            del self._valuable_protocol_prices[protocol]
            self._price_disagreements.append(peer)
        return True

    def _handle_info_price_response(self, response_dict, peer, request, protocol):
        if not request.response_identifier in response_dict:
            return InvalidResponseError("response identifier not in response")
        assert protocol in self._info_protocol_prices
        response = response_dict[request.response_identifier]
        if response == "RATE_ACCEPTED":
            return True
        else:
            del self._info_protocol_prices[protocol]
            self._price_disagreements.append(peer)
        return True

    def _request_failed(self, reason, request_type, peer):
        if reason.check(RequestCanceledError):
            return
        if reason.check(NoResponseError):
            self._incompatible_peers.append(peer)
            return
        logging.warning("Valuable blob info requester: a request of type %s has failed. Reason: %s",
                        str(request_type), str(reason.getErrorMessage()))
        self._update_local_score(peer, -10.0)
        peer.update_score(-5.0)
        if reason.check(ConnectionClosedBeforeResponseError):
            return
        # Only unexpected errors should be returned, as they are indicative of real problems
        # and may be shown to the user.
        return reason

    def _search_for_peers(self):
        references_with_sources = set()
        for h_list in self._peer_search_results.itervalues():
            for h in h_list:
                if h in self._valuable_hashes:
                    references_with_sources.add(self._valuable_hashes[h][1])
        hash_to_search = None
        used_references = []
        for h, (s, r, p) in self._valuable_hashes.iteritems():
            if not r in used_references:
                used_references.append(r)
                hash_to_search = h
                if not r in references_with_sources:
                    break
        if hash_to_search:
            d = self.peer_finder.find_peers_for_blob(hash_to_search)
            d.addCallback(self._set_peer_search_results, hash_to_search)

    def _set_peer_search_results(self, peers, searched_hash):
        for peer in peers:
            self._peer_search_results[peer].append(searched_hash)