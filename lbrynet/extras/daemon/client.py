import sys
import code
import argparse
import asyncio
import logging.handlers
from twisted.internet import defer, reactor, threads
from aiohttp import client_exceptions

from lbrynet import utils, conf, log_support
from lbrynet.extras.daemon import analytics
from lbrynet.extras.daemon.Daemon import Daemon
import json
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
        to_auth = json.dumps(pre_auth_post_data, sort_keys=True)
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
        api_key_name = key_name or "api"
        keyring = Keyring.load_from_disk()  # pylint: disable=E0602

        api_key = keyring.api_key
        login_url = conf.settings.get_api_connection_string(api_key_name, api_key.secret)
        url = urlparse(login_url)

        headers = {
            'Host': url.hostname,
            'User-Agent': USER_AGENT,
            'Content-type': 'application/json'
        }
        connector = aiohttp.TCPConnector(ssl=None if not conf.settings['use_https'] else keyring.ssl_context)
        session = aiohttp.ClientSession(connector=connector)

        async with session.post(login_url, headers=headers) as r:
            cookies = r.cookies
        uid = cookies.get(TWISTED_SECURE_SESSION if conf.settings['use_https'] else TWISTED_SESSION).value
        api_key = APIKey.create(seed=uid.encode())  # pylint: disable=E0602
        return cls(api_key, session, cookies, url, login_url)


class LBRYAPIClient:
    @staticmethod
    def get_client(conf_path=None):
        conf.conf_file = conf_path
        if not conf.settings:
            conf.initialize_settings()
        return AuthAPIClient.get_client() if conf.settings['use_auth_http'] else \
            UnAuthAPIClient.from_url(conf.settings.get_api_connection_string())


if sys.platform.startswith('darwin') or sys.platform.startswith('linux'):
    def color(msg, c="white"):
        _colors = {
            "normal": (0, 37),
            "underlined": (2, 37),
            "red": (1, 31),
            "green": (1, 32),
            "yellow": (1, 33),
            "blue": (1, 33),
            "magenta": (1, 34),
            "cyan": (1, 35),
            "white": (1, 36),
            "grey": (1, 37)
        }
        i, j = _colors[c]
        return "\033[%i;%i;40m%s\033[0m" % (i, j, msg)


    logo = """\
                            ╓▄█▄ç                           
                        ,▄█▓▓▀▀▀▓▓▓▌▄,                      
                     ▄▄▓▓▓▀¬      ╙▀█▓▓▓▄▄                  
                 ,▄█▓▓▀▀              ^▀▀▓▓▓▌▄,             
              ▄█▓▓█▀`                      ╙▀█▓▓▓▄▄         
          ╓▄▓▓▓▀╙                               ▀▀▓▓▓▌▄,    
       ▄█▓▓█▀                                       ╙▀▓▓    
   ╓▄▓▓▓▀`                                        ▄█▓▓▓▀    
  ▓▓█▀                                        ,▄▓▓▓▀╙       
  ▓▓m   ╟▌▄,                               ▄█▓▓█▀     ,,╓µ  
  ▓▓m   ^▀█▓▓▓▄▄                       ╓▄▓▓▓▀╙     █▓▓▓▓▓▀  
  ▓▓Q       '▀▀▓▓▓▌▄,              ,▄█▓▓█▀       ▄█▓▓▓▓▓▀   
  ▀▓▓▓▌▄,        ╙▀█▓▓█▄╗       ╓▄▓▓▓▀       ╓▄▓▓▓▀▀  ▀▀    
     ╙▀█▓▓█▄╗        ^▀▀▓▓▓▌▄▄█▓▓▀▀       ▄█▓▓█▀`           
         '▀▀▓▓▓▌▄,        ╙▀██▀`      ╓▄▓▓▓▀╙               
              ╙▀█▓▓█▄╥            ,▄█▓▓▀▀                   
                  └▀▀▓▓▓▌▄     ▄▒▓▓▓▀╙                      
                       ╙▀█▓▓█▓▓▓▀▀                          
                           ╙▀▀`                             
                                                            
"""
else:
    def color(msg, c=None):
        return msg

    logo = """\
                     '.                    
                    ++++.                  
                  +++,;+++,                
                :+++    :+++:              
               +++        ,+++;            
             '++;           .+++'          
           `+++               `++++        
          +++.                  `++++      
        ;+++                       ++++    
       +++                           +++   
     +++:                             '+   
   ,+++                              +++   
  +++`                             +++:    
 `+'                             ,+++      
 `+   +                         +++        
 `+   +++                     '++'  :'+++: 
 `+    ++++                 `+++     ++++  
 `+      ++++              +++.     :+++'  
 `+,       ++++          ;+++      +++++   
 `+++,       ++++       +++      +++;  +   
   ,+++,       ++++   +++:     .+++        
     ,+++:       '++++++      +++`         
       ,+++:       '++      '++'           
         ,+++:            `+++             
           .+++;         +++,              
             .+++;     ;+++                
               .+++;  +++                  
                 `+++++:                   
                   `++
                              
"""

welcometext = """\
For a list of available commands:
    >>>help()

To see the documentation for a given command:
    >>>help("resolve")

To exit:
    >>>exit()
"""

welcome = "{:*^60}\n".format(" Welcome to the lbrynet interactive console! ")
welcome += "\n".join([f"{w:<60}" for w in welcometext.splitlines()])
welcome += "\n%s" % ("*" * 60)
welcome = color(welcome, "grey")
banner = color(logo, "green") + color(welcome, "grey")


def get_methods(daemon):
    locs = {}

    def wrapped(name, fn):
        client = LBRYAPIClient.get_client()
        _fn = getattr(client, name)
        _fn.__doc__ = fn.__doc__
        return {name: _fn}

    for method_name, method in daemon.callable_methods.items():
        locs.update(wrapped(method_name, method))
    return locs


def run_terminal(callable_methods, started_daemon, quiet=False):
    locs = {}
    locs.update(callable_methods)

    def help(method_name=None):
        if not method_name:
            print("Available api functions: ")
            for name in callable_methods:
                print("\t%s" % name)
            return
        if method_name not in callable_methods:
            print("\"%s\" is not a recognized api function")
            return
        print(callable_methods[method_name].__doc__)
        return

    locs.update({'help': help})

    if started_daemon:
        def exit(status=None):
            if not quiet:
                print("Stopping lbrynet-daemon...")
            callable_methods['daemon_stop']()
            return sys.exit(status)

        locs.update({'exit': exit})
    else:
        def exit(status=None):
            try:
                reactor.callLater(0, reactor.stop)
            except Exception as err:
                print(f"error stopping reactor: {err}")
            return sys.exit(status)

        locs.update({'exit': exit})

    code.interact(banner if not quiet else "", local=locs)


@defer.inlineCallbacks
def start_server_and_listen(use_auth, analytics_manager, quiet):
    log_support.configure_console()
    logging.getLogger("lbrynet").setLevel(logging.CRITICAL)
    logging.getLogger("lbryum").setLevel(logging.CRITICAL)
    logging.getLogger("requests").setLevel(logging.CRITICAL)

    # TODO: turn this all into async. Until then this routine can't be called
    # analytics_manager.send_server_startup()
    yield Daemon().start_listening()


def threaded_terminal(started_daemon, quiet):
    callable_methods = get_methods(Daemon)
    d = threads.deferToThread(run_terminal, callable_methods, started_daemon, quiet)
    d.addErrback(lambda err: err.trap(SystemExit))
    d.addErrback(log.exception)


async def start_lbrynet_console(quiet, use_existing_daemon, useauth):
    if not utils.check_connection():
        print("Not connected to internet, unable to start")
        raise Exception("Not connected to internet, unable to start")
    if not quiet:
        print("Starting lbrynet-console...")
    try:
        await LBRYAPIClient.get_client().status()
        d = defer.succeed(False)
        if not quiet:
            print("lbrynet-daemon is already running, connecting to it...")
    except client_exceptions.ClientConnectorError:
        if not use_existing_daemon:
            if not quiet:
                print("Starting lbrynet-daemon...")
            analytics_manager = analytics.Manager.new_instance()
            d = start_server_and_listen(useauth, analytics_manager, quiet)
        else:
            raise Exception("cannot connect to an existing daemon instance, "
                            "and set to not start a new one")
    d.addCallback(threaded_terminal, quiet)
    d.addErrback(log.exception)


def main():
    conf.initialize_settings()
    parser = argparse.ArgumentParser(description="Launch lbrynet-daemon")
    parser.add_argument(
        "--use_existing_daemon",
        help="Start lbrynet-daemon if it isn't already running",
        action="store_true",
        default=False,
        dest="use_existing_daemon"
    )
    parser.add_argument(
        "--quiet", dest="quiet", action="store_true", default=False
    )
    parser.add_argument(
        "--http-auth", dest="useauth", action="store_true", default=conf.settings['use_auth_http']
    )
    args = parser.parse_args()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_lbrynet_console(args.quiet, args.use_existing_daemon, args.useauth))
    reactor.run()


if __name__ == "__main__":
    main()
