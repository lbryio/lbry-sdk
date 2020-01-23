from aiohttp import web
from prometheus_client import Counter, Info, generate_latest as prom_generate_latest
from lbry.wallet.server import util
from lbry import __version__ as version
from lbry.build_type import BUILD, COMMIT_HASH

NAMESPACE = "wallet_server"

VERSION_INFO = Info('build_info', 'Wallet server build info (e.g. version, commit hash)', namespace=NAMESPACE)
VERSION_INFO.info({'version': version, 'build': BUILD, "commit": COMMIT_HASH})
REQUESTS_COUNT = Counter("requests_count", "Number of requests received", namespace=NAMESPACE)


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
