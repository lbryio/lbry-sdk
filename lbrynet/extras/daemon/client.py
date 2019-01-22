from lbrynet import conf
import aiohttp
import logging
from urllib.parse import urlparse


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


class UnAuthAPIClient:
    def __init__(self, host, port, session):
        self.host = host
        self.port = port
        self.session = session

    def __getattr__(self, method):
        async def f(*args, **kwargs):
            return await self.call(method, [args, kwargs])

        return f

    @classmethod
    async def from_url(cls, url):
        url_fragment = urlparse(url)
        host = url_fragment.hostname
        port = url_fragment.port
        connector = aiohttp.TCPConnector()
        session = aiohttp.ClientSession(connector=connector)
        return cls(host, port, session)

    async def call(self, method, params=None):
        message = {'method': method, 'params': params}
        async with self.session.get(conf.settings.get_api_connection_string(), json=message) as resp:
            response_dict = await resp.json()
        if 'error' in response_dict:
            raise JSONRPCException(response_dict['error'])
        else:
            return response_dict['result']


class LBRYAPIClient:
    @staticmethod
    def get_client(conf_path=None):
        conf.conf_file = conf_path
        if not conf.settings:
            conf.initialize_settings()
        return UnAuthAPIClient.from_url(conf.settings.get_api_connection_string())
