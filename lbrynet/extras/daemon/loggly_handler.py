import asyncio
import aiohttp
import json
import logging.handlers
import traceback
from lbrynet import utils, __version__


class JsonFormatter(logging.Formatter):
    """Format log records using json serialization"""

    def __init__(self, **kwargs):
        self.attributes = kwargs

    def format(self, record):
        data = {
            'loggerName': record.name,
            'asciTime': self.formatTime(record),
            'fileName': record.filename,
            'functionName': record.funcName,
            'levelNo': record.levelno,
            'lineNo': record.lineno,
            'levelName': record.levelname,
            'message': record.getMessage(),
        }
        data.update(self.attributes)
        if record.exc_info:
            data['exc_info'] = self.formatException(record.exc_info)
        return json.dumps(data)


class HTTPSLogglyHandler(logging.Handler):
    def __init__(self, loggly_token: str, fqdn=False, localname=None, facility=None, cookies=None):
        super().__init__()
        self.fqdn = fqdn
        self.localname = localname
        self.facility = facility
        self.cookies = cookies or {}
        self.url = "https://logs-01.loggly.com/inputs/{token}/tag/{tag}".format(
            token=utils.deobfuscate(loggly_token), tag='lbrynet-' + __version__
        )

    def get_full_message(self, record):
        if record.exc_info:
            return '\n'.join(traceback.format_exception(*record.exc_info))
        else:
            return record.getMessage()

    async def _emit(self, record):
        payload = self.format(record)
        async with aiohttp.request('post', self.url, data=payload.encode(), cookies=self.cookies) as response:
            self.cookies.update(response.cookies)

    def emit(self, record):
        asyncio.get_running_loop().create_task(self._emit(record))


def get_loggly_handler(loggly_token):
    handler = HTTPSLogglyHandler(loggly_token)
    handler.setFormatter(JsonFormatter())
    handler.name = "loggly"
    return handler
