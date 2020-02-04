import os
from aiohttp import web
from prometheus_client import Counter, Info, generate_latest as prom_generate_latest, Histogram, Gauge
from lbry import __version__ as version
from lbry.build_info import BUILD, COMMIT_HASH, DOCKER_TAG
from lbry.wallet.server import util
import lbry.wallet.server.version as wallet_server_version

NAMESPACE = "wallet_server"
CPU_COUNT = f"{os.cpu_count()}"
VERSION_INFO = Info('build', 'Wallet server build info (e.g. version, commit hash)', namespace=NAMESPACE)
VERSION_INFO.info({
    'build': BUILD,
    "commit": COMMIT_HASH,
    "docker_tag": DOCKER_TAG,
    'version': version,
    "min_version": util.version_string(wallet_server_version.PROTOCOL_MIN),
    "cpu_count": CPU_COUNT
})
SESSIONS_COUNT = Gauge("session_count", "Number of connected client sessions", namespace=NAMESPACE,
                       labelnames=("version", ))
REQUESTS_COUNT = Counter("requests_count", "Number of requests received", namespace=NAMESPACE,
                         labelnames=("method", "version"))
RESPONSE_TIMES = Histogram("response_time", "Response times", namespace=NAMESPACE, labelnames=("method", "version"))
NOTIFICATION_COUNT = Counter("notification", "Number of notifications sent (for subscriptions)",
                             namespace=NAMESPACE, labelnames=("method", "version"))
REQUEST_ERRORS_COUNT = Counter("request_error", "Number of requests that returned errors", namespace=NAMESPACE,
                               labelnames=("method", "version"))
SQLITE_INTERRUPT_COUNT = Counter("interrupt", "Number of interrupted queries", namespace=NAMESPACE)
SQLITE_OPERATIONAL_ERROR_COUNT = Counter(
    "operational_error", "Number of queries that raised operational errors", namespace=NAMESPACE
)
SQLITE_INTERNAL_ERROR_COUNT = Counter(
    "internal_error", "Number of queries raising unexpected errors", namespace=NAMESPACE
)
SQLITE_EXECUTOR_TIMES = Histogram("executor_time", "SQLite executor times", namespace=NAMESPACE)
SQLITE_PENDING_COUNT = Gauge(
    "pending_queries_count", "Number of pending and running sqlite queries", namespace=NAMESPACE
)
LBRYCRD_REQUEST_TIMES = Histogram(
    "lbrycrd_request", "lbrycrd requests count", namespace=NAMESPACE, labelnames=("method",)
)
LBRYCRD_PENDING_COUNT = Gauge(
    "lbrycrd_pending_count", "Number of lbrycrd rpcs that are in flight", namespace=NAMESPACE, labelnames=("method",)
)
CLIENT_VERSIONS = Counter(
    "clients", "Number of connections received per client version",
    namespace=NAMESPACE, labelnames=("version",)
)
BLOCK_COUNT = Gauge(
    "block_count", "Number of processed blocks", namespace=NAMESPACE
)
BLOCK_UPDATE_TIMES = Histogram("block_time", "Block update times", namespace=NAMESPACE)


class PrometheusServer:
    def __init__(self):
        self.logger = util.class_logger(__name__, self.__class__.__name__)
        self.runner = None

    async def start(self, port: int):
        prom_app = web.Application()
        prom_app.router.add_get('/metrics', self.handle_metrics_get_request)
        self.runner = web.AppRunner(prom_app)
        await self.runner.setup()

        metrics_site = web.TCPSite(self.runner, "0.0.0.0", port, shutdown_timeout=.5)
        await metrics_site.start()
        self.logger.info('metrics server listening on %s:%i', *metrics_site._server.sockets[0].getsockname()[:2])

    async def handle_metrics_get_request(self, request: web.Request):
        try:
            return web.Response(
                text=prom_generate_latest().decode(),
                content_type='text/plain; version=0.0.4'
            )
        except Exception:
            self.logger.exception('could not generate prometheus data')
            raise

    async def stop(self):
        await self.runner.cleanup()
