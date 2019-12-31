import asyncio
from aiohttp.client_exceptions import ClientError
import json
import logging.handlers
import traceback
import aiohttp
from lbry import utils, __version__


LOGGLY_TOKEN = 'BQEzZmMzLJHgAGxkBF00LGD0YGuyATVgAmqxAQEuAQZ2BQH4'


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
        self._loop = asyncio.get_event_loop()
        self._session = aiohttp.ClientSession()

    def get_full_message(self, record):
        if record.exc_info:
            return '\n'.join(traceback.format_exception(*record.exc_info))
        else:
            return record.getMessage()

    async def _emit(self, record, retry=True):
        data = self.format(record).encode()
        try:
            async with self._session.post(self.url, data=data,
                                          cookies=self.cookies) as response:
                self.cookies.update(response.cookies)
        except ClientError:
            if self._loop.is_running() and retry:
                await self._session.close()
                self._session = aiohttp.ClientSession()
                return await self._emit(record, retry=False)

    def emit(self, record):
        asyncio.ensure_future(self._emit(record))

    def close(self):
        super().close()
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self._session.close())
        except RuntimeError:
            pass


def get_loggly_handler():
    handler = HTTPSLogglyHandler(LOGGLY_TOKEN)
    handler.setFormatter(JsonFormatter())
    return handler
