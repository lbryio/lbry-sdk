import time
import logging
import asyncio
import asyncio.tasks
from aiohttp import web
from prometheus_client import generate_latest as prom_generate_latest
from prometheus_client import Counter, Histogram, Gauge


PROBES_IN_FLIGHT = Counter("probes_in_flight", "Number of loop probes in flight", namespace='asyncio')
PROBES_FINISHED = Counter("probes_finished", "Number of finished loop probes", namespace='asyncio')
PROBE_TIMES = Histogram("probe_times", "Loop probe times", namespace='asyncio')
TASK_COUNT = Gauge("running_tasks", "Number of running tasks", namespace='asyncio')


def get_loop_metrics(delay=1):
    loop = asyncio.get_event_loop()

    def callback(started):
        PROBE_TIMES.observe(time.perf_counter() - started - delay)
        PROBES_FINISHED.inc()

    async def monitor_loop_responsiveness():
        while True:
            now = time.perf_counter()
            loop.call_later(delay, callback, now)
            PROBES_IN_FLIGHT.inc()
            TASK_COUNT.set(len(asyncio.tasks._all_tasks))
            await asyncio.sleep(delay)

    return loop.create_task(monitor_loop_responsiveness())


class PrometheusServer:
    def __init__(self, logger=None):
        self.runner = None
        self.logger = logger or logging.getLogger(__name__)
        self._monitor_loop_task = None

    async def start(self, interface: str, port: int):
        self.logger.info("start prometheus metrics")
        prom_app = web.Application()
        prom_app.router.add_get('/metrics', self.handle_metrics_get_request)
        self.runner = web.AppRunner(prom_app)
        await self.runner.setup()

        metrics_site = web.TCPSite(self.runner, interface, port, shutdown_timeout=.5)
        await metrics_site.start()
        self.logger.info(
            'prometheus metrics server listening on %s:%i', *metrics_site._server.sockets[0].getsockname()[:2]
        )
        self._monitor_loop_task = get_loop_metrics()

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
        if self._monitor_loop_task and not self._monitor_loop_task.done():
            self._monitor_loop_task.cancel()
        self._monitor_loop_task = None
        await self.runner.cleanup()
