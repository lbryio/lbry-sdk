import asyncio
import json
import logging.handlers
import traceback

from aiohttp.client_exceptions import ClientError
import aiohttp
from lbry import utils, __version__


LOGGLY_TOKEN = 'BQEzZmMzLJHgAGxkBF00LGD0YGuyATVgAmqxAQEuAQZ2BQH4'


class JsonFormatter(logging.Formatter):
    """Format log records using json serialization"""

    def __init__(self, **kwargs):
        super().__init__()
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
    def __init__(self, loggly_token: str, fqdn=False, localname=None, facility=None, cookies=None, feature_toggle=None):
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
        self._toggle = feature_toggle

    @property
    def enabled(self):
        return self._toggle is None or (self._toggle and self._toggle())

    @staticmethod
    def get_full_message(record):
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
            if self._loop.is_running() and retry and self.enabled:
                await self._session.close()
                self._session = aiohttp.ClientSession()
                return await self._emit(record, retry=False)

    def emit(self, record):
        if not self.enabled:
            return
        try:
            asyncio.ensure_future(self._emit(record), loop=self._loop)
        except RuntimeError:  # TODO: use a second loop
            print(f"\nfailed to send traceback to loggly, please file an issue with the following traceback:\n"
                  f"{self.format(record)}")

    def close(self):
        super().close()
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self._session.close())
        except RuntimeError:
            pass


def get_loggly_handler(feature_toggle):
    handler = HTTPSLogglyHandler(LOGGLY_TOKEN, feature_toggle=feature_toggle)
    handler.setFormatter(JsonFormatter())
    return handler
