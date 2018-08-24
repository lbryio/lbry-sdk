import os
import json
import aiohttp
import logging
from urllib.parse import urlparse

from lbrynet import conf
from lbrynet.daemon.auth.util import load_api_keys, APIKey, API_KEY_NAME, get_auth_message

log = logging.getLogger(__name__)
USER_AGENT = "AuthServiceProxy/0.1"
TWISTED_SESSION = "TWISTED_SESSION"
LBRY_SECRET = "LBRY_SECRET"
HTTP_TIMEOUT = 30
SCHEME = "http"


class JSONRPCException(Exception):
    def __init__(self, rpc_error):
        super().__init__()
        self.error = rpc_error


class UnAuthAPIClient:
    def __init__(self, host, port, session):
        self.host = host
        self.port = port
        self.session = session
        self.scheme = SCHEME

    def __getattr__(self, method):
        async def f(*args, **kwargs):
            return await self.call(method, [args, kwargs])

        return f

    @classmethod
    async def from_url(cls, url):
        url_fragment = urlparse(url)
        host = url_fragment.hostname
        port = url_fragment.port
        session = aiohttp.ClientSession()
        return cls(host, port, session)

    async def call(self, method, params=None):
        message = {'method': method, 'params': params}
        async with self.session.get('{}://{}:{}'.format(self.scheme, self.host, self.port), json=message) as resp:
            return await resp.json()


class AuthAPIClient:
    def __init__(self, key, session, cookies, url, login_url):
        self.session = session
        self.__api_key = key
        self.__login_url = login_url
        self.__id_count = 0
        self.__url = url
        self.__cookies = cookies

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)

        def f(*args, **kwargs):
            return self.call(name, [args, kwargs])

        return f

    async def call(self, method, params=None):
        params = params or {}
        self.__id_count += 1

        pre_auth_post_data = {
            'version': '2',
            'method': method,
            'params': params,
            'id': self.__id_count
        }
        to_auth = get_auth_message(pre_auth_post_data)
        auth_msg = self.__api_key.get_hmac(to_auth).decode()
        pre_auth_post_data.update({'hmac': auth_msg})
        post_data = json.dumps(pre_auth_post_data)

        headers = {
            'Host': self.__url.hostname,
            'User-Agent': USER_AGENT,
            'Content-type': 'application/json'
        }

        async with self.session.post(self.__login_url, data=post_data, headers=headers) as resp:
            if resp is None:
                raise JSONRPCException({'code': -342, 'message': 'missing HTTP response from server'})
            resp.raise_for_status()

            next_secret = resp.headers.get(LBRY_SECRET, False)
            if next_secret:
                self.__api_key.secret = next_secret

            return await resp.json()

    @classmethod
    async def get_client(cls, key_name=None):
        api_key_name = key_name or API_KEY_NAME

        pw_path = os.path.join(conf.settings['data_dir'], ".api_keys")
        keys = load_api_keys(pw_path)
        api_key = keys.get(api_key_name, False)

        login_url = "http://{}:{}@{}:{}".format(api_key_name, api_key.secret, conf.settings['api_host'],
                                                conf.settings['api_port'])
        url = urlparse(login_url)

        headers = {
            'Host': url.hostname,
            'User-Agent': USER_AGENT,
            'Content-type': 'application/json'
        }

        session = aiohttp.ClientSession()

        async with session.post(login_url, headers=headers) as r:
            cookies = r.cookies

        uid = cookies.get(TWISTED_SESSION).value
        api_key = APIKey.new(seed=uid.encode())
        return cls(api_key, session, cookies, url, login_url)


class LBRYAPIClient:
    @staticmethod
    def get_client(conf_path=None):
        conf.conf_file = conf_path
        if not conf.settings:
            conf.initialize_settings()
        return AuthAPIClient.get_client() if conf.settings['use_auth_http'] else \
            UnAuthAPIClient.from_url(conf.settings.get_api_connection_string())
