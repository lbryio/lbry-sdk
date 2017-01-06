import itertools
import logging

from twisted.internet import defer


log = logging.getLogger(__name__)


class DeferredPool(defer.Deferred):
    def __init__(self, deferred_iter, pool_size):
        self.deferred_iter = deferred_iter
        self.pool_size = pool_size
        # results are stored unordered
        self.result_list = []
        self.started_count = 0
        self.total_count = None
        defer.Deferred.__init__(self)

        for deferred in itertools.islice(deferred_iter, pool_size):
            self._start_one(deferred)

    def _start_one(self, deferred):
        deferred.addCallbacks(self._callback, self._callback,
                              callbackArgs=(self.started_count, defer.SUCCESS),
                              errbackArgs=(self.started_count, defer.FAILURE))
        self.started_count += 1

    def _callback(self, result, index, success):
        self.result_list.append((index, success, result))
        if self._done():
            self._finish()
        else:
            self._process_next()
        return result

    def _done(self):
        return self.total_count  == len(self.result_list)

    def _finish(self):
        result_list = [(s, r) for i, s, r in sorted(self.result_list)]
        self.callback(result_list)

    def _process_next(self):
        try:
            deferred = next(self.deferred_iter)
        except StopIteration:
            self.total_count = self.started_count
        else:
            self._start_one(deferred)
