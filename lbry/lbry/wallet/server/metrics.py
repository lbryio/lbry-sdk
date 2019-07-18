import time
import math
from typing import Tuple


def calculate_elapsed(start) -> int:
    return int((time.perf_counter() - start) * 1000)


def calculate_percentiles(data) -> Tuple[int, int, int, int, int, int, int]:
    if not data:
        return 0, 0, 0, 0, 0, 0, 0
    data.sort()
    size = len(data)
    return (
        data[0],
        data[math.ceil(size * .05) - 1],
        data[math.ceil(size * .25) - 1],
        data[math.ceil(size * .50) - 1],
        data[math.ceil(size * .75) - 1],
        data[math.ceil(size * .95) - 1],
        data[-1]
    )


def avg(data) -> int:
    return int(sum(data) / len(data)) if data else 0


def remove_select_list(sql) -> str:
    return sql[sql.index('FROM'):]


class APICallMetrics:

    def __init__(self, name):
        self.name = name
        # total counts
        self.cache_hits = 0
        self.started = 0
        self.errored = 0
        self.errored_queries = set()
        self.interrupted = 0
        self.interrupted_queries = set()
        # timings
        self.command_total_times = []
        self.command_query_times = []
        self.command_execution_times = []
        self.command_wait_times = []
        self.individual_query_times = []

    def to_json_and_reset(self):
        return {
            # total counts
            "cache_hits_count": self.cache_hits,
            "started_count": self.started,
            "finished_count": len(self.command_total_times),
            "errored_count": self.errored,
            "errored_queries": list(self.errored_queries),
            "interrupted_count": self.interrupted,
            "interrupted_queries": list(self.interrupted_queries),
            "individual_queries_count": len(self.individual_query_times),
            # timings and percentiles
            "total_avg": avg(self.command_total_times),
            "total_percentiles": calculate_percentiles(self.command_total_times),
            "query_avg": avg(self.command_query_times),
            "query_percentiles": calculate_percentiles(self.command_query_times),
            "execution_avg": avg(self.command_execution_times),
            "execution_percentiles": calculate_percentiles(self.command_execution_times),
            "wait_avg": avg(self.command_wait_times),
            "wait_percentiles": calculate_percentiles(self.command_wait_times),
            "individual_query_avg": avg(self.individual_query_times),
            "individual_query_percentiles": calculate_percentiles(self.individual_query_times),
        }

    def cache_hit(self):
        self.cache_hits += 1

    def start(self):
        self.started += 1

    def finish(self, start, metrics):
        self.command_total_times.append(calculate_elapsed(start))
        if metrics and 'execute_query' in metrics:
            query_times = [f['total'] for f in metrics['execute_query']]
            self.individual_query_times.extend(query_times)
            command_query_time = sum(query_times)
            self.command_query_times.append(command_query_time)
            self.command_execution_times.append(
                metrics[self.name][0]['total'] - command_query_time
            )
            self.command_wait_times.append(
                self.command_total_times[-1] - metrics[self.name][0]['total']
            )

    def _add_queries(self, metrics, query_set):
        if metrics and 'execute_query' in metrics:
            for execute_query in metrics['execute_query']:
                if 'sql' in execute_query:
                    query_set.add(remove_select_list(execute_query['sql']))

    def interrupt(self, start, metrics):
        self.finish(start, metrics)
        self._add_queries(metrics, self.interrupted_queries)

    def error(self, start, metrics=None):
        self.errored += 1
        if metrics:
            self.finish(start, metrics)
            self._add_queries(metrics, self.errored_queries)


class ServerLoadData:

    def __init__(self):
        self._apis = {}

    def for_api(self, name) -> APICallMetrics:
        if name not in self._apis:
            self._apis[name] = APICallMetrics(name)
        return self._apis[name]

    def to_json_and_reset(self, server):
        try:
            return {
                'api': {name: api.to_json_and_reset() for name, api in self._apis.items()},
                'server': server
            }
        finally:
            self._apis = {}
