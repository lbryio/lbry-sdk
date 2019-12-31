import time
import unittest
from lbry.wallet.server.metrics import ServerLoadData, calculate_avg_percentiles


class TestPercentileCalculation(unittest.TestCase):

    def test_calculate_percentiles(self):
        self.assertEqual(calculate_avg_percentiles([]), (0, 0, 0, 0, 0, 0, 0, 0))
        self.assertEqual(calculate_avg_percentiles([1]), (1, 1, 1, 1, 1, 1, 1, 1))
        self.assertEqual(calculate_avg_percentiles([1, 2]), (1, 1, 1, 1, 1, 2, 2, 2))
        self.assertEqual(calculate_avg_percentiles([1, 2, 3]), (2, 1, 1, 1, 2, 3, 3, 3))
        self.assertEqual(calculate_avg_percentiles([4, 1, 2, 3]), (2, 1, 1, 1, 2, 3, 4, 4))
        self.assertEqual(calculate_avg_percentiles([1, 2, 3, 4, 5, 6]), (3, 1, 1, 2, 3, 5, 6, 6))
        self.assertEqual(calculate_avg_percentiles(
            list(range(1, 101))), (50, 1, 5, 25, 50, 75, 95, 100))


class TestCollectingMetrics(unittest.TestCase):

    def test_happy_path(self):
        self.maxDiff = None
        load = ServerLoadData()
        search = load.for_api('search')
        self.assertEqual(search.name, 'search')
        search.start()
        search.cache_response()
        search.cache_response()
        metrics = {
            'search': [{'total': 40}],
            'execute_query': [
                {'total': 20},
                {'total': 10}
            ]
        }
        for x in range(5):
            search.query_response(time.perf_counter() - 0.055 + 0.001*x, metrics)
        metrics['execute_query'][0]['total'] = 10
        metrics['execute_query'][0]['sql'] = "select lots, of, stuff FROM claim where something=1"
        search.query_interrupt(time.perf_counter() - 0.050, metrics)
        search.query_error(time.perf_counter() - 0.050, metrics)
        search.query_error(time.perf_counter() - 0.052, {})
        self.assertEqual(load.to_json_and_reset({}), {'status': {}, 'api': {'search': {
            "receive_count": 1,
            "cache_response_count": 2,
            "query_response_count": 5,
            "intrp_response_count": 1,
            "error_response_count": 2,
            "response": (53, 51, 51, 52, 53, 54, 55, 55),
            "interrupt": (50, 50, 50, 50, 50, 50, 50, 50),
            "error": (51, 50, 50, 50, 50, 52, 52, 52),
            "python": (12, 10, 10, 10, 10, 20, 20, 20),
            "wait": (12, 10, 10, 10, 12, 14, 15, 15),
            "sql": (27, 20, 20, 20, 30, 30, 30, 30),
            "individual_sql": (13, 10, 10, 10, 10, 20, 20, 20),
            "individual_sql_count": 14,
            "errored_queries": ['FROM claim where something=1'],
            "interrupted_queries": ['FROM claim where something=1'],
        }}})
        self.assertEqual(load.to_json_and_reset({}), {'status': {}, 'api': {}})
