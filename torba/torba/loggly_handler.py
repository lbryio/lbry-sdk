import asyncio
import json
import codecs
import base64
import logging.handlers
import aiohttp
from aiohttp.client_exceptions import ClientError


def deobfuscate(obfustacated):
    return base64.b64decode(codecs.encode(obfustacated, 'rot_13')(obfustacated)).decode()


class JsonFormatter(logging.Formatter):
    """Format log records using json serialization"""

    def __init__(self, **kwargs):
        super().__init__()
        self.attributes = kwargs

    def format(self, record: logging.LogRecord):
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
    def __init__(self, loggly_token: str, tag: str, fqdn=False, localname=None, facility=None, cookies=None):
        super().__init__()
        self.fqdn = fqdn
        self.localname = localname
        self.facility = facility
        self.cookies = cookies or {}
        self.url = f"https://logs-01.loggly.com/inputs/{deobfuscate(loggly_token)}/tag/{tag}"
        self._loop = asyncio.get_event_loop()
        self._session = aiohttp.ClientSession(loop=self._loop)

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


def get_loggly_handler(tag: str, token: str, level=logging.ERROR) -> HTTPSLogglyHandler:
    handler = HTTPSLogglyHandler(token, tag)
    handler.setFormatter(JsonFormatter())
    handler.setLevel(level)
    return handler
