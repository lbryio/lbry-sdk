import sys
from twisted.internet import asyncioreactor
if 'twisted.internet.reactor' not in sys.modules:
    asyncioreactor.install()
else:
    from twisted.internet import reactor
    if not isinstance(reactor, asyncioreactor.AsyncioSelectorReactor):
        # pyinstaller hooks install the default reactor before
        # any of our code runs, see kivy for similar problem:
        #    https://github.com/kivy/kivy/issues/4182
        del sys.modules['twisted.internet.reactor']
        asyncioreactor.install()

import json
import asyncio
from aiohttp.client_exceptions import ClientConnectorError
from requests.exceptions import ConnectionError
from docopt import docopt
from textwrap import dedent

from lbrynet.daemon.Daemon import Daemon
from lbrynet.daemon.DaemonControl import start as daemon_main
from lbrynet.daemon.DaemonConsole import main as daemon_console
from lbrynet.daemon.auth.client import LBRYAPIClient
from lbrynet.core.system_info import get_platform


async def execute_command(method, params, conf_path=None):
    # this check if the daemon is running or not
    try:
        api = await LBRYAPIClient.get_client(conf_path)
        await api.status()
    except (ClientConnectorError, ConnectionError):
        await api.session.close()
        print("Could not connect to daemon. Are you sure it's running?")
        return 1

    # this actually executes the method
    try:
        resp = await api.call(method, params)
        await api.session.close()
        print(json.dumps(resp["result"], indent=2))
    except KeyError:
        if resp["error"]["code"] == -32500:
            print(json.dumps(resp["error"], indent=2))
        else:
            print(json.dumps(resp["error"]["message"], indent=2))


def print_help():
    print(dedent("""
    NAME
       lbrynet - LBRY command line client.
    
    USAGE
       lbrynet [--conf <config file>] <command> [<args>]
    
    EXAMPLES
       lbrynet commands                 # list available commands
       lbrynet status                   # get daemon status
       lbrynet --conf ~/l1.conf status  # like above but using ~/l1.conf as config file
       lbrynet resolve_name what        # resolve a name
       lbrynet help resolve_name        # get help for a command
    """))


def print_help_for_command(command):
    fn = Daemon.callable_methods.get(command)
    if fn:
        print(dedent(fn.__doc__))
    else:
        print("Invalid command name")


def normalize_value(x, key=None):
    if not isinstance(x, str):
        return x
    if key in ('uri', 'channel_name', 'name', 'file_name', 'download_directory'):
        return x
    if x.lower() == 'true':
        return True
    if x.lower() == 'false':
        return False
    if x.isdigit():
        return int(x)
    return x


def remove_brackets(key):
    if key.startswith("<") and key.endswith(">"):
        return str(key[1:-1])
    return key


def set_kwargs(parsed_args):
    kwargs = {}
    for key, arg in parsed_args.items():
        k = None
        if arg is None:
            continue
        elif key.startswith("--") and remove_brackets(key[2:]) not in kwargs:
            k = remove_brackets(key[2:])
        elif remove_brackets(key) not in kwargs:
            k = remove_brackets(key)
        kwargs[k] = normalize_value(arg, k)
    return kwargs


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print_help()
        return 1

    conf_path = None
    if len(argv) and argv[0] == "--conf":
        if len(argv) < 2:
            print("No config file specified for --conf option")
            print_help()
            return 1

        conf_path = argv[1]
        argv = argv[2:]

    method, args = argv[0], argv[1:]

    if method in ['help', '--help', '-h']:
        if len(args) == 1:
            print_help_for_command(args[0])
        else:
            print_help()
        return 0

    elif method in ['version', '--version', '-v']:
        print(json.dumps(get_platform(get_ip=False), sort_keys=True, indent=2, separators=(',', ': ')))
        return 0

    elif method == 'start':
        sys.exit(daemon_main(args, conf_path))

    elif method == 'console':
        sys.exit(daemon_console())

    elif method not in Daemon.callable_methods:
        if method not in Daemon.deprecated_methods:
            print('{} is not a valid command.'.format(method))
            return 1
        new_method = Daemon.deprecated_methods[method].new_command
        print("{} is deprecated, using {}.".format(method, new_method))
        method = new_method

    fn = Daemon.callable_methods[method]
    parsed = docopt(fn.__doc__, args)
    params = set_kwargs(parsed)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(execute_command(method, params, conf_path))

    return 0


if __name__ == "__main__":
    sys.exit(main())
