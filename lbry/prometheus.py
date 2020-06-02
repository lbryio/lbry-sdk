import logging
from aiohttp import web
from prometheus_client import generate_latest as prom_generate_latest


class PrometheusServer:
    def __init__(self, logger=None):
        self.runner = None
        self.logger = logger or logging.getLogger(__name__)

    async def start(self, interface: str, port: int):
        prom_app = web.Application()
        prom_app.router.add_get('/metrics', self.handle_metrics_get_request)
        self.runner = web.AppRunner(prom_app)
        await self.runner.setup()

        metrics_site = web.TCPSite(self.runner, interface, port, shutdown_timeout=.5)
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
