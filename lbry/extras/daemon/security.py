import logging
from aiohttp import web

log = logging.getLogger(__name__)


def ensure_request_allowed(request, conf):
    if is_request_allowed(request, conf):
        return
    if conf.allowed_origin:
        log.warning(
            "API requests with Origin '%s' are not allowed, "
            "configuration 'allowed_origin' limits requests to: '%s'",
            request.headers.get('Origin'), conf.allowed_origin
        )
    else:
        log.warning(
            "API requests with Origin '%s' are not allowed, "
            "update configuration 'allowed_origin' to enable this origin.",
            request.headers.get('Origin')
        )
    raise web.HTTPForbidden()


def is_request_allowed(request, conf) -> bool:
    origin = request.headers.get('Origin', 'null')
    if origin == 'null' or conf.allowed_origin in ('*', origin):
        return True
    return False
