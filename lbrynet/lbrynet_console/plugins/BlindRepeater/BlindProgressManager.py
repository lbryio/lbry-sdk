from zope.interface import implements
from lbrynet.interfaces import IProgressManager
from twisted.internet import defer


class BlindProgressManager(object):
    implements(IProgressManager)

    def __init__(self, blob_manager, peers, max_space, blob_scorers, download_manager):
        self.blob_manager = blob_manager
        self.peers = peers
        self.max_space = max_space
        self.blob_scorers = blob_scorers
        self.download_manager = download_manager
        self.paused = True
        self.blobs_to_download = []
        self._next_manage_downloaded_blobs = None

    def set_max_space(self, max_space):
        self.max_space = max_space

    ######### IProgressManager #########

    def start(self):
        from twisted.internet import reactor

        self.paused = False
        self._next_manage_downloaded_blobs = reactor.callLater(0, self._manage_downloaded_blobs)
        return defer.succeed(True)

    def stop(self):
        self.paused = True
        if self._next_manage_downloaded_blobs is not None and self._next_manage_downloaded_blobs.active():
            self._next_manage_downloaded_blobs.cancel()
        self._next_manage_downloaded_blobs = None
        return defer.succeed(True)

    def stream_position(self):
        return 0

    def needed_blobs(self):
        needed_blobs = [b for b in self.blobs_to_download if not b.is_validated()]
        return sorted(needed_blobs, key=lambda x: x.is_downloading(), reverse=True)[:20]

    ######### internal #########

    def _manage_downloaded_blobs(self):

        self._next_manage_downloaded_blobs = None

        from twisted.internet import reactor

        blobs = self.download_manager.blobs
        blob_infos = self.download_manager.blob_infos

        blob_hashes = [b.blob_hash for b in blobs]

        blobs_to_score = [(blobs[blob_hash], blob_infos[blob_hash]) for blob_hash in blob_hashes]

        scores = self._score_blobs(blobs_to_score)

        from future_builtins import zip

        scored_blobs = zip(blobs_to_score, scores)
        ranked_blobs = sorted(scored_blobs, key=lambda x: x[1], reverse=True)

        space_so_far = 0
        blobs_to_delete = []
        blobs_to_download = []

        for (blob, blob_info), score in ranked_blobs:
            space_so_far += blob.blob_length
            if blob.is_validated() and space_so_far >= self.max_space:
                blobs_to_delete.append(blob)
            elif not blob.is_validated() and space_so_far < self.max_space:
                blobs_to_download.append(blob)

        self.blob_manager.delete_blobs(blobs_to_delete)
        self.blobs_to_download = blobs_to_download

        self._next_manage_downloaded_blobs = reactor.callLater(30, self._manage_downloaded_blobs)

    def _score_blobs(self, blobs):
        scores = []
        for blob, blob_info in blobs:
            summands = []
            multiplicands = []
            for blob_scorer in self.blob_scorers:
                s, m = blob_scorer.score_blob(blob, blob_info)
                summands.append(s)
                multiplicands.append(m)
            scores.append(1.0 * sum(summands) * reduce(lambda x, y: x * y, multiplicands, 1))
        return scores