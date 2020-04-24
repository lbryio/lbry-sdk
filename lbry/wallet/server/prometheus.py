import os
from prometheus_client import Counter, Info, Histogram, Gauge
from lbry import __version__ as version
from lbry.build_info import BUILD, COMMIT_HASH, DOCKER_TAG
from lbry.wallet.server import util
import lbry.wallet.server.version as wallet_server_version


class PrometheusMetrics:
    VERSION_INFO: Info
    SESSIONS_COUNT: Gauge
    REQUESTS_COUNT: Counter
    RESPONSE_TIMES: Histogram
    NOTIFICATION_COUNT: Counter
    REQUEST_ERRORS_COUNT: Counter
    SQLITE_INTERRUPT_COUNT: Counter
    SQLITE_OPERATIONAL_ERROR_COUNT: Counter
    SQLITE_INTERNAL_ERROR_COUNT: Counter
    SQLITE_EXECUTOR_TIMES: Histogram
    SQLITE_PENDING_COUNT: Gauge
    LBRYCRD_REQUEST_TIMES: Histogram
    LBRYCRD_PENDING_COUNT: Gauge
    CLIENT_VERSIONS: Counter
    BLOCK_COUNT: Gauge
    BLOCK_UPDATE_TIMES: Histogram
    REORG_COUNT: Gauge
    RESET_CONNECTIONS: Counter

    __slots__ = [
        'VERSION_INFO',
        'SESSIONS_COUNT',
        'REQUESTS_COUNT',
        'RESPONSE_TIMES',
        'NOTIFICATION_COUNT',
        'REQUEST_ERRORS_COUNT',
        'SQLITE_INTERRUPT_COUNT',
        'SQLITE_OPERATIONAL_ERROR_COUNT',
        'SQLITE_INTERNAL_ERROR_COUNT',
        'SQLITE_EXECUTOR_TIMES',
        'SQLITE_PENDING_COUNT',
        'LBRYCRD_REQUEST_TIMES',
        'LBRYCRD_PENDING_COUNT',
        'CLIENT_VERSIONS',
        'BLOCK_COUNT',
        'BLOCK_UPDATE_TIMES',
        'REORG_COUNT',
        'RESET_CONNECTIONS',
        '_installed',
        'namespace',
        'cpu_count'
    ]

    def __init__(self):
        self._installed = False
        self.namespace = "wallet_server"
        self.cpu_count = f"{os.cpu_count()}"

    def uninstall(self):
        self._installed = False
        for item in self.__slots__:
            if not item.startswith('_') and item not in ('namespace', 'cpu_count'):
                current = getattr(self, item, None)
                if current:
                    setattr(self, item, None)
                    del current

    def install(self):
        if self._installed:
            return
        self._installed = True
        self.VERSION_INFO = Info('build', 'Wallet server build info (e.g. version, commit hash)', namespace=self.namespace)
        self.VERSION_INFO.info({
            'build': BUILD,
            "commit": COMMIT_HASH,
            "docker_tag": DOCKER_TAG,
            'version': version,
            "min_version": util.version_string(wallet_server_version.PROTOCOL_MIN),
            "cpu_count": self.cpu_count
        })
        self.SESSIONS_COUNT = Gauge("session_count", "Number of connected client sessions", namespace=self.namespace,
                                    labelnames=("version",))
        self.REQUESTS_COUNT = Counter("requests_count", "Number of requests received", namespace=self.namespace,
                                      labelnames=("method", "version"))
        self.RESPONSE_TIMES = Histogram("response_time", "Response times", namespace=self.namespace,
                                        labelnames=("method", "version"))
        self.NOTIFICATION_COUNT = Counter("notification", "Number of notifications sent (for subscriptions)",
                                          namespace=self.namespace, labelnames=("method", "version"))
        self.REQUEST_ERRORS_COUNT = Counter("request_error", "Number of requests that returned errors", namespace=self.namespace,
                                            labelnames=("method", "version"))
        self.SQLITE_INTERRUPT_COUNT = Counter("interrupt", "Number of interrupted queries", namespace=self.namespace)
        self.SQLITE_OPERATIONAL_ERROR_COUNT = Counter(
            "operational_error", "Number of queries that raised operational errors", namespace=self.namespace
        )
        self.SQLITE_INTERNAL_ERROR_COUNT = Counter(
            "internal_error", "Number of queries raising unexpected errors", namespace=self.namespace
        )
        self.SQLITE_EXECUTOR_TIMES = Histogram("executor_time", "SQLite executor times", namespace=self.namespace)
        self.SQLITE_PENDING_COUNT = Gauge(
            "pending_queries_count", "Number of pending and running sqlite queries", namespace=self.namespace
        )
        self.LBRYCRD_REQUEST_TIMES = Histogram(
            "lbrycrd_request", "lbrycrd requests count", namespace=self.namespace, labelnames=("method",)
        )
        self.LBRYCRD_PENDING_COUNT = Gauge(
            "lbrycrd_pending_count", "Number of lbrycrd rpcs that are in flight", namespace=self.namespace,
            labelnames=("method",)
        )
        self.CLIENT_VERSIONS = Counter(
            "clients", "Number of connections received per client version",
            namespace=self.namespace, labelnames=("version",)
        )
        self.BLOCK_COUNT = Gauge(
            "block_count", "Number of processed blocks", namespace=self.namespace
        )
        self.BLOCK_UPDATE_TIMES = Histogram("block_time", "Block update times", namespace=self.namespace)
        self.REORG_COUNT = Gauge(
            "reorg_count", "Number of reorgs", namespace=self.namespace
        )
        self.RESET_CONNECTIONS = Counter(
            "reset_clients", "Number of reset connections by client version",
            namespace=self.namespace, labelnames=("version",)
        )


METRICS = PrometheusMetrics()
