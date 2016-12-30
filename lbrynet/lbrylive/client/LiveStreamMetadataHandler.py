# pylint: skip-file
from collections import defaultdict
import logging
from zope.interface import implements
from twisted.internet import defer
from twisted.python.failure import Failure
from lbrynet import conf
from lbrynet.core.client.ClientRequest import ClientRequest, ClientPaidRequest
from lbrynet.lbrylive.LiveBlob import LiveBlobInfo
from lbrynet.core.cryptoutils import get_lbry_hash_obj, verify_signature
from lbrynet.interfaces import IRequestCreator, IMetadataHandler
from lbrynet.core.Error import InsufficientFundsError, InvalidResponseError, RequestCanceledError
from lbrynet.core.Error import NoResponseError, ConnectionClosedBeforeResponseError


log = logging.getLogger(__name__)


class LiveStreamMetadataHandler(object):
    implements(IRequestCreator, IMetadataHandler)

    def __init__(self, stream_hash, stream_info_manager, peer_finder, stream_pub_key, download_whole,
                 payment_rate_manager, wallet, download_manager, max_before_skip_ahead=None):
        self.stream_hash = stream_hash
        self.stream_info_manager = stream_info_manager
        self.payment_rate_manager = payment_rate_manager
        self.wallet = wallet
        self.peer_finder = peer_finder
        self.stream_pub_key = stream_pub_key
        self.download_whole = download_whole
        self.max_before_skip_ahead = max_before_skip_ahead
        if self.download_whole is False:
            assert self.max_before_skip_ahead is not None, \
                "If download whole is False, max_before_skip_ahead must be set"
        self.download_manager = download_manager
        self._peers = defaultdict(int)  # {Peer: score}
        self._protocol_prices = {}
        self._final_blob_num = None
        self._price_disagreements = []  # [Peer]
        self._incompatible_peers = []  # [Peer]

    ######### IMetadataHandler #########

    def get_initial_blobs(self):
        d = self.stream_info_manager.get_blobs_for_stream(self.stream_hash)
        d.addCallback(self._format_initial_blobs_for_download_manager)
        return d

    def final_blob_num(self):
        return self._final_blob_num

    ######## IRequestCreator #########

    def send_next_request(self, peer, protocol):
        if self._finished_discovery() is False and self._should_send_request_to(peer) is True:
            p_r = None
            if not self._price_settled(protocol):
                p_r = self._get_price_request(peer, protocol)
            d_r = self._get_discover_request(peer)
            reserved_points = self._reserve_points(peer, protocol, d_r.max_pay_units)
            if reserved_points is not None:
                d1 = protocol.add_request(d_r)
                d1.addCallback(self._handle_discover_response, peer, d_r)
                d1.addBoth(self._pay_or_cancel_payment, protocol, reserved_points)
                d1.addErrback(self._request_failed, peer)
                if p_r is not None:
                    d2 = protocol.add_request(p_r)
                    d2.addCallback(self._handle_price_response, peer, p_r, protocol)
                    d2.addErrback(self._request_failed, peer)
                return defer.succeed(True)
            else:
                return defer.fail(InsufficientFundsError())
        return defer.succeed(False)

    def get_new_peers(self):
        d = self._get_hash_for_peer_search()
        d.addCallback(self._find_peers_for_hash)
        return d

    ######### internal calls #########

    def _get_hash_for_peer_search(self):
        r = None
        if self._finished_discovery() is False:
            r = self.stream_hash
        log.debug("Info finder peer search response for stream %s: %s", str(self.stream_hash), str(r))
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
            return d

    def _format_initial_blobs_for_download_manager(self, blob_infos):
        infos = []
        for blob_hash, blob_num, revision, iv, length, signature in blob_infos:
            if blob_hash is not None:
                infos.append(LiveBlobInfo(blob_hash, blob_num, length, iv, revision, signature))
            else:
                log.debug("Setting _final_blob_num to %s", str(blob_num - 1))
                self._final_blob_num = blob_num - 1
        return infos

    def _should_send_request_to(self, peer):
        if self._peers[peer] < -5.0:
            return False
        if peer in self._price_disagreements:
            return False
        return True

    def _get_bad_peers(self):
        return [p for p in self._peers.iterkeys() if not self._should_send_request_to(p)]

    def _finished_discovery(self):
        if self._get_discovery_params() is None:
            return True
        return False

    def _get_discover_request(self, peer):
        discovery_params = self._get_discovery_params()
        if discovery_params:
            further_blobs_request = {}
            reference, start, end, count = discovery_params
            further_blobs_request['reference'] = reference
            if start is not None:
                further_blobs_request['start'] = start
            if end is not None:
                further_blobs_request['end'] = end
            if count is not None:
                further_blobs_request['count'] = count
            else:
                further_blobs_request['count'] = conf.settings.MAX_BLOB_INFOS_TO_REQUEST
            log.debug("Requesting %s blob infos from %s", str(further_blobs_request['count']), str(peer))
            r_dict = {'further_blobs': further_blobs_request}
            response_identifier = 'further_blobs'
            request = ClientPaidRequest(r_dict, response_identifier, further_blobs_request['count'])
            return request
        return None

    def _get_discovery_params(self):
        log.debug("In _get_discovery_params")
        stream_position = self.download_manager.stream_position()
        blobs = self.download_manager.blobs
        if blobs:
            last_blob_num = max(blobs.iterkeys())
        else:
            last_blob_num = -1
        final_blob_num = self.final_blob_num()
        if final_blob_num is not None:
            last_blob_num = final_blob_num
        if self.download_whole is False:
            log.debug("download_whole is False")
            if final_blob_num is not None:
                for i in xrange(stream_position, final_blob_num + 1):
                    if not i in blobs:
                        count = min(self.max_before_skip_ahead, (final_blob_num - i + 1))
                        return self.stream_hash, None, 'end', count
                return None
            else:
                if blobs:
                    for i in xrange(stream_position, last_blob_num + 1):
                        if not i in blobs:
                            if i == 0:
                                return self.stream_hash, 'beginning', 'end', -1 * self.max_before_skip_ahead
                            else:
                                return self.stream_hash, blobs[i-1].blob_hash, 'end', -1 * self.max_before_skip_ahead
                    return self.stream_hash, blobs[last_blob_num].blob_hash, 'end', -1 * self.max_before_skip_ahead
                else:
                    return self.stream_hash, None, 'end', -1 * self.max_before_skip_ahead
        log.debug("download_whole is True")
        beginning = None
        end = None
        for i in xrange(stream_position, last_blob_num + 1):
            if not i in blobs:
                if beginning is None:
                    if i == 0:
                        beginning = 'beginning'
                    else:
                        beginning = blobs[i-1].blob_hash
            else:
                if beginning is not None:
                    end = blobs[i].blob_hash
                    break
        if beginning is None:
            if final_blob_num is not None:
                log.debug("Discovery is finished. stream_position: %s, last_blob_num + 1: %s", str(stream_position),
                          str(last_blob_num + 1))
                return None
            else:
                log.debug("Discovery is not finished. final blob num is unknown.")
                if last_blob_num != -1:
                    return self.stream_hash, blobs[last_blob_num].blob_hash, None, None
                else:
                    return self.stream_hash, 'beginning', None, None
        else:
            log.info("Discovery is not finished. Not all blobs are known.")
            return self.stream_hash, beginning, end, None

    def _price_settled(self, protocol):
        if protocol in self._protocol_prices:
            return True
        return False

    def _update_local_score(self, peer, amount):
        self._peers[peer] += amount

    def _reserve_points(self, peer, protocol, max_infos):
        assert protocol in self._protocol_prices
        point_amount = 1.0 * max_infos * self._protocol_prices[protocol] / 1000.0
        return self.wallet.reserve_points(peer, point_amount)

    def _pay_or_cancel_payment(self, arg, protocol, reserved_points):
        if isinstance(arg, Failure) or arg == 0:
            self._cancel_points(reserved_points)
        else:
            self._pay_peer(protocol, arg, reserved_points)
        return arg

    def _pay_peer(self, protocol, num_infos, reserved_points):
        assert num_infos != 0
        assert protocol in self._protocol_prices
        point_amount = 1.0 * num_infos * self._protocol_prices[protocol] / 1000.0
        self.wallet.send_points(reserved_points, point_amount)
        self.payment_rate_manager.record_points_paid(point_amount)

    def _cancel_points(self, reserved_points):
        return self.wallet.cancel_point_reservation(reserved_points)

    def _get_price_request(self, peer, protocol):
        self._protocol_prices[protocol] = self.payment_rate_manager.get_rate_live_blob_info(peer)
        request_dict = {'blob_info_payment_rate': self._protocol_prices[protocol]}
        request = ClientRequest(request_dict, 'blob_info_payment_rate')
        return request

    def _handle_price_response(self, response_dict, peer, request, protocol):
        if not request.response_identifier in response_dict:
            return InvalidResponseError("response identifier not in response")
        assert protocol in self._protocol_prices
        response = response_dict[request.response_identifier]
        if response == "RATE_ACCEPTED":
            return True
        else:
            log.info("Rate offer has been rejected by %s", str(peer))
            del self._protocol_prices[protocol]
            self._price_disagreements.append(peer)
        return True

    def _handle_discover_response(self, response_dict, peer, request):
        if not request.response_identifier in response_dict:
            return InvalidResponseError("response identifier not in response")
        response = response_dict[request.response_identifier]
        blob_infos = []
        if 'error' in response:
            if response['error'] == 'RATE_UNSET':
                return defer.succeed(0)
            else:
                return InvalidResponseError("Got an unknown error from the peer: %s" %
                                            (response['error'],))
        if not 'blob_infos' in response:
            return InvalidResponseError("Missing the required field 'blob_infos'")
        raw_blob_infos = response['blob_infos']
        log.info("Handling %s further blobs from %s", str(len(raw_blob_infos)), str(peer))
        log.debug("blobs: %s", str(raw_blob_infos))
        for raw_blob_info in raw_blob_infos:
            length = raw_blob_info['length']
            if length != 0:
                blob_hash = raw_blob_info['blob_hash']
            else:
                blob_hash = None
            num = raw_blob_info['blob_num']
            revision = raw_blob_info['revision']
            iv = raw_blob_info['iv']
            signature = raw_blob_info['signature']
            blob_info = LiveBlobInfo(blob_hash, num, length, iv, revision, signature)
            log.debug("Learned about a potential blob: %s", str(blob_hash))
            if self._verify_blob(blob_info):
                if blob_hash is None:
                    log.info("Setting _final_blob_num to %s", str(num - 1))
                    self._final_blob_num = num - 1
                else:
                    blob_infos.append(blob_info)
            else:
                raise ValueError("Peer sent an invalid blob info")
        d = self.stream_info_manager.add_blobs_to_stream(self.stream_hash, blob_infos)

        def add_blobs_to_download_manager():
            blob_nums = [b.blob_num for b in blob_infos]
            log.info("Adding the following blob nums to the download manager: %s", str(blob_nums))
            self.download_manager.add_blobs_to_download(blob_infos)

        d.addCallback(lambda _: add_blobs_to_download_manager())

        def pay_or_penalize_peer():
            if len(blob_infos):
                self._update_local_score(peer, len(blob_infos))
                peer.update_stats('downloaded_crypt_blob_infos', len(blob_infos))
                peer.update_score(len(blob_infos))
            else:
                self._update_local_score(peer, -.0001)
            return len(blob_infos)

        d.addCallback(lambda _: pay_or_penalize_peer())

        return d

    def _verify_blob(self, blob):
        log.debug("Got an unverified blob to check:")
        log.debug("blob_hash: %s", blob.blob_hash)
        log.debug("blob_num: %s", str(blob.blob_num))
        log.debug("revision: %s", str(blob.revision))
        log.debug("iv: %s", blob.iv)
        log.debug("length: %s", str(blob.length))
        hashsum = get_lbry_hash_obj()
        hashsum.update(self.stream_hash)
        if blob.length != 0:
            hashsum.update(blob.blob_hash)
        hashsum.update(str(blob.blob_num))
        hashsum.update(str(blob.revision))
        hashsum.update(blob.iv)
        hashsum.update(str(blob.length))
        log.debug("hexdigest to be verified: %s", hashsum.hexdigest())
        if verify_signature(hashsum.digest(), blob.signature, self.stream_pub_key):
            log.debug("Blob info is valid")
            return True
        else:
            log.debug("The blob info is invalid")
            return False

    def _request_failed(self, reason, peer):
        if reason.check(RequestCanceledError):
            return
        if reason.check(NoResponseError):
            self._incompatible_peers.append(peer)
        log.warning("Crypt stream info finder: a request failed. Reason: %s", reason.getErrorMessage())
        self._update_local_score(peer, -5.0)
        peer.update_score(-10.0)
        if reason.check(ConnectionClosedBeforeResponseError):
            return
        return reason
