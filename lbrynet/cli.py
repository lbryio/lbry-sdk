import sys
import asyncio
import aiohttp
from docopt import docopt
from textwrap import dedent

from lbrynet.daemon.Daemon import Daemon
from lbrynet.daemon.DaemonControl import start


async def execute_command(command, args):
    message = {'method': command, 'params': args}
    async with aiohttp.ClientSession() as session:
        async with session.get('http://localhost:5279/lbryapi', json=message) as resp:
            print(await resp.json())


def print_help():
    print(dedent("""
    NAME
       lbry - LBRY command line client.
    
    USAGE
       lbry [--conf <config file>] <command> [<args>]
    
    EXAMPLES
       lbry commands                 # list available commands
       lbry status                   # get daemon status
       lbry --conf ~/l1.conf status  # like above but using ~/l1.conf as config file
       lbry resolve_name what        # resolve a name
       lbry help resolve_name        # get help for a command
    """))


def print_help_for_command(command):
    print("@hackrush didn't implement this yet :-p")


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


def main(argv):
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
        print("@hackrush didn't implement this yet :-p")

    elif method == 'start':
        start(args)

    elif method not in Daemon.callable_methods:
        print('"{}" is not a valid command.'.format(method))
        return 1

    else:
        fn = Daemon.callable_methods[method]
        parsed = docopt(fn.__doc__, args)
        kwargs = set_kwargs(parsed)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(execute_command(method, kwargs))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
