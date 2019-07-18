import time
import unittest
from lbry.wallet.server.metrics import ServerLoadData, calculate_percentiles


class TestPercentileCalculation(unittest.TestCase):

    def test_calculate_percentiles(self):
        self.assertEqual(calculate_percentiles([]), [0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(calculate_percentiles([1]), [1, 1, 1, 1, 1, 1, 1])
        self.assertEqual(calculate_percentiles([1, 2]), [1, 1, 1, 1, 2, 2, 2])
        self.assertEqual(calculate_percentiles([1, 2, 3]), [1, 1, 1, 2, 3, 3, 3])
        self.assertEqual(calculate_percentiles([1, 2, 3, 4]), [1, 1, 1, 2, 3, 4, 4])
        self.assertEqual(calculate_percentiles([1, 2, 3, 4, 5, 6]), [1, 1, 2, 3, 5, 6, 6])
        self.assertEqual(calculate_percentiles(list(range(1, 101))), [1, 5, 25, 50, 75, 95, 100])


class TestCollectingMetrics(unittest.TestCase):

    def test_happy_path(self):
        self.maxDiff = None
        load = ServerLoadData()
        search = load.for_api('search')
        self.assertEqual(search.name, 'search')
        search.start()
        search.cache_hit()
        search.cache_hit()
        metrics = {
            'search': [{'total': 40}],
            'execute_query': [
                {'total': 20},
                {'total': 10}
            ]
        }
        for x in range(5):
            search.finish(time.perf_counter() - 0.055 + 0.001*x, metrics)
        metrics['execute_query'][0]['total'] = 10
        metrics['execute_query'][0]['sql'] = "select lots, of, stuff FROM claim where something=1"
        search.interrupt(time.perf_counter() - 0.050, metrics)
        search.error(time.perf_counter() - 0.050, metrics)
        search.error(time.perf_counter() - 0.052)
        self.assertEqual(load.to_json_and_reset({}), {'status': {}, 'api': {'search': {
            'cache_hits_count': 2,
            'errored_count': 2,
            'errored_queries': ['FROM claim where something=1'],
            'execution_avg': 12,
            'execution_percentiles': (10, 10, 10, 10, 20, 20, 20),
            'finished_count': 7,
            'individual_queries_count': 14,
            'individual_query_avg': 13,
            'individual_query_percentiles': (10, 10, 10, 10, 20, 20, 20),
            'interrupted_count': 0,
            'interrupted_queries': ['FROM claim where something=1'],
            'query_avg': 27,
            'query_percentiles': (20, 20, 20, 30, 30, 30, 30),
            'started_count': 1,
            'total_avg': 52,
            'total_percentiles': (50, 50, 50, 52, 54, 55, 55),
            'wait_avg': 12,
            'wait_percentiles': (10, 10, 10, 12, 14, 15, 15)
        }}})
        self.assertEqual(load.to_json_and_reset({}), {'status': {}, 'api': {}})
