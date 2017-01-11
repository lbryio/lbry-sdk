import urlparse
import logging
import requests
import os
import base64
import json

from lbrynet.lbrynet_daemon.auth.util import load_api_keys, APIKey, API_KEY_NAME, get_auth_message
from lbrynet import conf
from jsonrpc.proxy import JSONRPCProxy

log = logging.getLogger(__name__)
USER_AGENT = "AuthServiceProxy/0.1"
TWISTED_SESSION = "TWISTED_SESSION"
LBRY_SECRET = "LBRY_SECRET"
HTTP_TIMEOUT = 30


class JSONRPCException(Exception):
    def __init__(self, rpc_error):
        Exception.__init__(self)
        self.error = rpc_error


class AuthAPIClient(object):
    def __init__(self, key, timeout, connection, count, cookies, auth, url, login_url):
        self.__api_key = key
        self.__service_url = login_url
        self.__id_count = count
        self.__url = url
        self.__auth_header = auth
        self.__conn = connection
        self.__cookies = cookies

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError  # Python internal stuff

        def f(*args):
            return self.call(name, args[0] if args else {})

        return f

    def call(self, method, params={}):
        self.__id_count += 1
        pre_auth_post_data = {
            'version': '1.1',
            'method': method,
            'params': [params],
            'id': self.__id_count
        }
        to_auth = get_auth_message(pre_auth_post_data)
        token = self.__api_key.get_hmac(to_auth)
        pre_auth_post_data.update({'hmac': token})
        post_data = json.dumps(pre_auth_post_data)
        service_url = self.__service_url
        auth_header = self.__auth_header
        cookies = self.__cookies
        host = self.__url.hostname

        req = requests.Request(method='POST',
                               url=service_url,
                               data=post_data,
                               headers={
                                   'Host': host,
                                   'User-Agent': USER_AGENT,
                                   'Authorization': auth_header,
                                   'Content-type': 'application/json'
                               },
                               cookies=cookies)
        r = req.prepare()
        http_response = self.__conn.send(r)
        cookies = http_response.cookies
        headers = http_response.headers
        next_secret = headers.get(LBRY_SECRET, False)
        if next_secret:
            self.__api_key.secret = next_secret
            self.__cookies = cookies

        if http_response is None:
            raise JSONRPCException({
                'code': -342, 'message': 'missing HTTP response from server'})

        http_response.raise_for_status()

        response = http_response.json()

        if response['error'] is not None:
            raise JSONRPCException(response['error'])
        elif 'result' not in response:
            raise JSONRPCException({
                'code': -343, 'message': 'missing JSON-RPC result'})
        else:
            return response['result']

    @classmethod
    def config(cls, key_name=None, key=None, pw_path=None,
               timeout=HTTP_TIMEOUT,
               connection=None, count=0,
               cookies=None, auth=None,
               url=None, login_url=None):

        api_key_name = API_KEY_NAME if not key_name else key_name
        pw_path = os.path.join(conf.settings.data_dir, ".api_keys") if not pw_path else pw_path
        if not key:
            keys = load_api_keys(pw_path)
            api_key = keys.get(api_key_name, False)
        else:
            api_key = APIKey(name=api_key_name, secret=key)
        if login_url is None:
            service_url = "http://%s:%s@%s:%i/%s" % (api_key_name,
                                                     api_key.secret,
                                                     conf.settings.API_INTERFACE,
                                                     conf.settings.api_port,
                                                     conf.settings.API_ADDRESS)
        else:
            service_url = login_url
        id_count = count

        if auth is None and connection is None and cookies is None and url is None:
            # This is a new client instance, initialize the auth header and start a session
            url = urlparse.urlparse(service_url)
            (user, passwd) = (url.username, url.password)
            try:
                user = user.encode('utf8')
            except AttributeError:
                pass
            try:
                passwd = passwd.encode('utf8')
            except AttributeError:
                pass
            authpair = user + b':' + passwd
            auth_header = b'Basic ' + base64.b64encode(authpair)
            conn = requests.Session()
            conn.auth = (user, passwd)
            req = requests.Request(method='POST',
                                   url=service_url,
                                   auth=conn.auth,
                                   headers={'Host': url.hostname,
                                            'User-Agent': USER_AGENT,
                                            'Authorization': auth_header,
                                            'Content-type': 'application/json'},)
            r = req.prepare()
            http_response = conn.send(r)
            cookies = http_response.cookies
            uid = cookies.get(TWISTED_SESSION)
            api_key = APIKey.new(seed=uid)
        else:
            # This is a client that already has a session, use it
            auth_header = auth
            conn = connection
            assert cookies.get(LBRY_SECRET, False), "Missing cookie"
            secret = cookies.get(LBRY_SECRET)
            api_key = APIKey(secret, api_key_name)
        return cls(api_key, timeout, conn, id_count, cookies, auth_header, url, service_url)


class LBRYAPIClient(object):
    @staticmethod
    def get_client():
        return AuthAPIClient.config() if conf.settings.use_auth_http else \
            JSONRPCProxy.from_url(conf.settings.API_CONNECTION_STRING)
