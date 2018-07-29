import sys
import json
import asyncio
from aiohttp import client_exceptions
from docopt import docopt
from textwrap import dedent

from lbrynet.daemon.auth.client import LBRYAPIClient
from lbrynet.core.system_info import get_platform
from lbrynet.daemon.Daemon import Daemon
from lbrynet.daemon.DaemonControl import start


async def execute_command(command, args):
    api = LBRYAPIClient.get_client()
    try:
        await api.status()
    except client_exceptions.ClientConnectorError:
        print("Could not connect to daemon. Are you sure it's running?")
        return 1

    try:
        resp = await api.call(command, args)
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


def guess_type(x, key=None):
    if not isinstance(x, str):
        return x
    if key in ('uri', 'channel_name', 'name', 'file_name', 'download_directory'):
        return x
    if x in ('true', 'True', 'TRUE'):
        return True
    if x in ('false', 'False', 'FALSE'):
        return False
    if '.' in x:
        try:
            return float(x)
        except ValueError:
            # not a float
            pass
    try:
        return int(x)
    except ValueError:
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
        kwargs[k] = guess_type(arg, k)
    return kwargs


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print_help()
        return 1

    method, args = argv[0], argv[1:]

    if method in ['help', '--help', '-h']:
        if len(args) == 1:
            print_help_for_command(args[0])
        else:
            print_help()

    elif method in ['version', '--version', '-v']:
        print(json.dumps(get_platform(get_ip=False), sort_keys=True, indent=4, separators=(',', ': ')))

    elif method == 'start':
        sys.exit(start(args))

    elif method not in Daemon.callable_methods:
        if method not in Daemon.deprecated_methods:
            print('"{}" is not a valid command.'.format(method))
            return 1
        new_method = Daemon.deprecated_methods[method].new_command
        print("{} is deprecated, using {}.".format(method, new_method))
        method = new_method

    fn = Daemon.callable_methods[method]
    parsed = docopt(fn.__doc__, args)
    kwargs = set_kwargs(parsed)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(execute_command(method, kwargs))

    return 0


if __name__ == "__main__":
    sys.exit(main())
