import os
import json
import urlparse
import requests
from requests.cookies import RequestsCookieJar
import logging
from jsonrpc.proxy import JSONRPCProxy
from lbrynet import conf
from lbrynet.daemon.auth.util import load_api_keys, APIKey, API_KEY_NAME, get_auth_message

log = logging.getLogger(__name__)
USER_AGENT = "AuthServiceProxy/0.1"
TWISTED_SESSION = "TWISTED_SESSION"
LBRY_SECRET = "LBRY_SECRET"
HTTP_TIMEOUT = 30


def copy_cookies(cookies):
    result = RequestsCookieJar()
    result.update(cookies)
    return result


class JSONRPCException(Exception):
    def __init__(self, rpc_error):
        Exception.__init__(self)
        self.error = rpc_error


class AuthAPIClient(object):
    def __init__(self, key, timeout, connection, count, cookies, url, login_url):
        self.__api_key = key
        self.__service_url = login_url
        self.__id_count = count
        self.__url = url
        self.__conn = connection
        self.__cookies = copy_cookies(cookies)

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)

        def f(*args, **kwargs):
            return self.call(name, [args, kwargs])

        return f

    def call(self, method, params=None):
        params = params or {}
        self.__id_count += 1
        pre_auth_post_data = {
            'version': '2',
            'method': method,
            'params': params,
            'id': self.__id_count
        }
        to_auth = get_auth_message(pre_auth_post_data)
        pre_auth_post_data.update({'hmac': self.__api_key.get_hmac(to_auth)})
        post_data = json.dumps(pre_auth_post_data)
        cookies = copy_cookies(self.__cookies)
        req = requests.Request(
            method='POST', url=self.__service_url, data=post_data, cookies=cookies,
            headers={
                        'Host': self.__url.hostname,
                        'User-Agent': USER_AGENT,
                        'Content-type': 'application/json'
            }
        )
        http_response = self.__conn.send(req.prepare())
        if http_response is None:
            raise JSONRPCException({
                'code': -342, 'message': 'missing HTTP response from server'})
        http_response.raise_for_status()
        next_secret = http_response.headers.get(LBRY_SECRET, False)
        if next_secret:
            self.__api_key.secret = next_secret
            self.__cookies = copy_cookies(http_response.cookies)
        response = http_response.json()
        if response.get('error') is not None:
            raise JSONRPCException(response['error'])
        elif 'result' not in response:
            raise JSONRPCException({
                'code': -343, 'message': 'missing JSON-RPC result'})
        else:
            return response['result']

    @classmethod
    def config(cls, key_name=None, key=None, pw_path=None, timeout=HTTP_TIMEOUT, connection=None, count=0,
               cookies=None, auth=None, url=None, login_url=None):

        api_key_name = key_name or API_KEY_NAME
        pw_path = os.path.join(conf.settings['data_dir'], ".api_keys") if not pw_path else pw_path
        if not key:
            keys = load_api_keys(pw_path)
            api_key = keys.get(api_key_name, False)
        else:
            api_key = APIKey(name=api_key_name, secret=key)
        if login_url is None:
            service_url = "http://%s:%s@%s:%i/%s" % (api_key_name,
                                                     api_key.secret,
                                                     conf.settings['api_host'],
                                                     conf.settings['api_port'],
                                                     conf.settings['API_ADDRESS'])
        else:
            service_url = login_url
        id_count = count

        if auth is None and connection is None and cookies is None and url is None:
            # This is a new client instance, start an authenticated session
            url = urlparse.urlparse(service_url)
            conn = requests.Session()
            req = requests.Request(method='POST',
                                   url=service_url,
                                   headers={'Host': url.hostname,
                                            'User-Agent': USER_AGENT,
                                            'Content-type': 'application/json'},)
            r = req.prepare()
            http_response = conn.send(r)
            cookies = RequestsCookieJar()
            cookies.update(http_response.cookies)
            uid = cookies.get(TWISTED_SESSION)
            api_key = APIKey.new(seed=uid)
        else:
            # This is a client that already has a session, use it
            conn = connection
            if not cookies.get(LBRY_SECRET):
                raise Exception("Missing cookie")
            secret = cookies.get(LBRY_SECRET)
            api_key = APIKey(secret, api_key_name)
        return cls(api_key, timeout, conn, id_count, cookies, url, service_url)


class LBRYAPIClient(object):
    @staticmethod
    def get_client():
        if not conf.settings:
            conf.initialize_settings()
        return AuthAPIClient.config() if conf.settings['use_auth_http'] else \
            JSONRPCProxy.from_url(conf.settings.get_api_connection_string())
