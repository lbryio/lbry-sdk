import time
import math
from typing import Tuple


def calculate_elapsed(start) -> int:
    return int((time.perf_counter() - start) * 1000)


def calculate_avg_percentiles(data) -> Tuple[int, int, int, int, int, int, int, int]:
    if not data:
        return 0, 0, 0, 0, 0, 0, 0, 0
    data.sort()
    size = len(data)
    return (
        int(sum(data) / size),
        data[0],
        data[math.ceil(size * .05) - 1],
        data[math.ceil(size * .25) - 1],
        data[math.ceil(size * .50) - 1],
        data[math.ceil(size * .75) - 1],
        data[math.ceil(size * .95) - 1],
        data[-1]
    )


def remove_select_list(sql) -> str:
    return sql[sql.index('FROM'):]


class APICallMetrics:

    def __init__(self, name):
        self.name = name

        # total requests received
        self.receive_count = 0
        self.cache_response_count = 0

        # millisecond timings for query based responses
        self.query_response_times = []
        self.query_intrp_times = []
        self.query_error_times = []

        self.query_python_times = []
        self.query_wait_times = []
        self.query_sql_times = []  # aggregate total of multiple SQL calls made per request

        self.individual_sql_times = []  # every SQL query run on server

        # actual queries
        self.errored_queries = set()
        self.interrupted_queries = set()

    def to_json_and_reset(self):
        return {
            # total requests received
            "receive_count": self.receive_count,
            # sum of these is total responses made
            "cache_response_count": self.cache_response_count,
            "query_response_count": len(self.query_response_times),
            "intrp_response_count": len(self.query_intrp_times),
            "error_response_count": len(self.query_error_times),
            # millisecond timings for non-cache responses
            "response": calculate_avg_percentiles(self.query_response_times),
            "interrupt": calculate_avg_percentiles(self.query_intrp_times),
            "error": calculate_avg_percentiles(self.query_error_times),
            # response, interrupt and error each also report the python, wait and sql stats:
            "python": calculate_avg_percentiles(self.query_python_times),
            "wait": calculate_avg_percentiles(self.query_wait_times),
            "sql": calculate_avg_percentiles(self.query_sql_times),
            # extended timings for individual sql executions
            "individual_sql": calculate_avg_percentiles(self.individual_sql_times),
            "individual_sql_count": len(self.individual_sql_times),
            # actual queries
            "errored_queries": list(self.errored_queries),
            "interrupted_queries": list(self.interrupted_queries),
        }

    def start(self):
        self.receive_count += 1

    def cache_response(self):
        self.cache_response_count += 1

    def _add_query_timings(self, request_total_time, metrics):
        if metrics and 'execute_query' in metrics:
            sub_process_total = metrics[self.name][0]['total']
            individual_query_times = [f['total'] for f in metrics['execute_query']]
            aggregated_query_time = sum(individual_query_times)
            self.individual_sql_times.extend(individual_query_times)
            self.query_sql_times.append(aggregated_query_time)
            self.query_python_times.append(sub_process_total - aggregated_query_time)
            self.query_wait_times.append(request_total_time - sub_process_total)

    @staticmethod
    def _add_queries(query_set, metrics):
        if metrics and 'execute_query' in metrics:
            for execute_query in metrics['execute_query']:
                if 'sql' in execute_query:
                    query_set.add(remove_select_list(execute_query['sql']))

    def query_response(self, start, metrics):
        self.query_response_times.append(calculate_elapsed(start))
        self._add_query_timings(self.query_response_times[-1], metrics)

    def query_interrupt(self, start, metrics):
        self.query_intrp_times.append(calculate_elapsed(start))
        self._add_queries(self.interrupted_queries, metrics)
        self._add_query_timings(self.query_intrp_times[-1], metrics)

    def query_error(self, start, metrics):
        self.query_error_times.append(calculate_elapsed(start))
        self._add_queries(self.errored_queries, metrics)
        self._add_query_timings(self.query_error_times[-1], metrics)


class ServerLoadData:

    def __init__(self):
        self._apis = {}

    def for_api(self, name) -> APICallMetrics:
        if name not in self._apis:
            self._apis[name] = APICallMetrics(name)
        return self._apis[name]

    def to_json_and_reset(self, status):
        try:
            return {
                'api': {name: api.to_json_and_reset() for name, api in self._apis.items()},
                'status': status
            }
        finally:
            self._apis = {}
