import aiohttp
import logging
from lbrynet.conf import Config

log = logging.getLogger(__name__)
USER_AGENT = "AuthServiceProxy/0.1"
TWISTED_SECURE_SESSION = "TWISTED_SECURE_SESSION"
TWISTED_SESSION = "TWISTED_SESSION"
LBRY_SECRET = "LBRY_SECRET"
HTTP_TIMEOUT = 30


class JSONRPCException(Exception):
    def __init__(self, rpc_error):
        super().__init__()
        self.error = rpc_error


class LBRYAPIClient:
    def __init__(self, conf: Config):
        self._conf = conf

    def __getattr__(self, method):
        async def f(*args, **kwargs):
            async with aiohttp.ClientSession() as session:
                message = {'method': method, 'params': [args, kwargs]}
                async with session.get(self._conf.api_connection_url, json=message) as resp:
                    data = await resp.json()
                    if 'result' in data:
                        return data['result']
                    elif 'error' in data:
                        raise JSONRPCException(data['error'])
        return f
