try:
    import http.client as httplib
except ImportError:
    import httplib
try:
    import urllib.parse as urlparse
except ImportError:
    import urlparse

import logging
import requests
import os
import base64
import json

from lbrynet.lbrynet_daemon.auth.util import load_api_keys, APIKey, API_KEY_NAME
from lbrynet.conf import API_INTERFACE, API_ADDRESS, API_PORT
from lbrynet.lbrynet_daemon.LBRYDaemon import log_dir as DATA_DIR

log = logging.getLogger(__name__)
USER_AGENT = "AuthServiceProxy/0.1"
HTTP_TIMEOUT = 30


class JSONRPCException(Exception):
    def __init__(self, rpc_error):
        Exception.__init__(self)
        self.error = rpc_error


class LBRYAPIClient(object):
    __api_token = None

    def __init__(self, key_name=None, key=None, pw_path=None, timeout=HTTP_TIMEOUT, connection=None, count=0,
                                            service=None, cookies=None, auth=None, url=None, login_url=None):
        self.__api_key_name = API_KEY_NAME if not key_name else key_name
        self.__api_token = key
        self.__pw_path = os.path.join(DATA_DIR, ".api_keys") if not pw_path else pw_path
        self.__service_name = service

        if not key:
            keys = load_api_keys(self.__pw_path)
            api_key = keys.get(self.__api_key_name, False)
            self.__api_token = api_key['token']
            self.__api_key_obj = api_key
        else:
            self.__api_key_obj = APIKey({'token': key})

        if login_url is None:
            self.__service_url = "http://%s:%s@%s:%i/%s" % (self.__api_key_name, self.__api_token,
                                                               API_INTERFACE, API_PORT, API_ADDRESS)
        else:
            self.__service_url = login_url

        self.__id_count = count

        if auth is None and connection is None and cookies is None and url is None:
            self.__url = urlparse.urlparse(self.__service_url)
            (user, passwd) = (self.__url.username, self.__url.password)
            try:
                user = user.encode('utf8')
            except AttributeError:
                pass
            try:
                passwd = passwd.encode('utf8')
            except AttributeError:
                pass
            authpair = user + b':' + passwd
            self.__auth_header = b'Basic ' + base64.b64encode(authpair)

            self.__conn = requests.Session()
            self.__conn.auth = (user, passwd)

            req = requests.Request(method='POST',
                                   url=self.__service_url,
                                   auth=self.__conn.auth,
                                   headers={'Host': self.__url.hostname,
                                            'User-Agent': USER_AGENT,
                                            'Authorization': self.__auth_header,
                                            'Content-type': 'application/json'},)
            r = req.prepare()
            http_response = self.__conn.send(r)
            cookies = http_response.cookies
            self.__cookies = cookies
            # print "Logged in"

            uid = cookies.get('TWISTED_SESSION')
            api_key = APIKey.new(seed=uid)
            # print "Created temporary api key"

            self.__api_token = api_key.token()
            self.__api_key_obj = api_key
        else:
            self.__auth_header = auth
            self.__conn = connection
            self.__cookies = cookies
            self.__url = url

            if cookies.get("secret", False):
                self.__api_token = cookies.get("secret")
            self.__api_key_obj = APIKey({'name': self.__api_key_name, 'token': self.__api_token})


    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            # Python internal stuff
            raise AttributeError
        if self.__service_name is not None:
            name = "%s.%s" % (self.__service_name, name)
        return LBRYAPIClient(key_name=self.__api_key_name,
                             key=self.__api_token,
                             connection=self.__conn,
                             service=name,
                             count=self.__id_count,
                             cookies=self.__cookies,
                             auth=self.__auth_header,
                             url=self.__url,
                             login_url=self.__service_url)

    def __call__(self, *args):
        self.__id_count += 1
        pre_auth_postdata = {'version': '1.1',
                             'method': self.__service_name,
                             'params': args,
                             'id': self.__id_count}
        to_auth = str(pre_auth_postdata['method']).encode('hex') + str(pre_auth_postdata['id']).encode('hex')
        token = self.__api_key_obj.get_hmac(to_auth.decode('hex'))
        pre_auth_postdata.update({'hmac': token})
        postdata = json.dumps(pre_auth_postdata)
        service_url = self.__service_url
        auth_header = self.__auth_header
        cookies = self.__cookies
        host = self.__url.hostname

        req = requests.Request(method='POST',
                               url=service_url,
                               data=postdata,
                               headers={'Host': host,
                                        'User-Agent': USER_AGENT,
                                        'Authorization': auth_header,
                                        'Content-type': 'application/json'},
                               cookies=cookies)
        r = req.prepare()
        http_response = self.__conn.send(r)
        self.__cookies = http_response.cookies
        headers = http_response.headers
        next_secret = headers.get('Next-Secret', False)

        if next_secret:
            cookies.update({'secret': next_secret})

        # print "Postdata: %s" % postdata
        if http_response is None:
            raise JSONRPCException({
                'code': -342, 'message': 'missing HTTP response from server'})

        # print "-----\n%s\n------" % http_response.text
        http_response.raise_for_status()

        response = http_response.json()

        if response['error'] is not None:
            raise JSONRPCException(response['error'])
        elif 'result' not in response:
            raise JSONRPCException({
                'code': -343, 'message': 'missing JSON-RPC result'})
        else:
            return response['result']