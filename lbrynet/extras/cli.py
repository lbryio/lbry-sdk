import sys
import os
import json
import asyncio
import argparse
import typing

# Set SSL_CERT_FILE env variable for Twisted SSL verification on Windows
# This needs to happen before anything else
if 'win' in sys.platform:
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()

from twisted.internet import asyncioreactor
if 'twisted.internet.reactor' not in sys.modules:
    asyncioreactor.install()
else:
    from twisted.internet import reactor
    if not isinstance(reactor, asyncioreactor.AsyncioSelectorReactor) and getattr(sys, 'frozen', False):
        # pyinstaller hooks install the default reactor before
        # any of our code runs, see kivy for similar problem:
        #    https://github.com/kivy/kivy/issues/4182
        del sys.modules['twisted.internet.reactor']
        asyncioreactor.install()
from twisted.internet import reactor
import logging
from aiohttp.client_exceptions import ClientConnectorError
from requests.exceptions import ConnectionError
from docopt import docopt
from textwrap import dedent

from lbrynet import conf, log_support, __name__ as lbrynet_name
from lbrynet.utils import check_connection, json_dumps_pretty
from lbrynet.extras.daemon.Daemon import Daemon
from lbrynet.extras.daemon.DaemonConsole import main as daemon_console, LBRYAPIClient
from lbrynet.extras.system_info import get_platform

log = logging.getLogger(lbrynet_name)

optional_path_getter_type = typing.Optional[typing.Callable[[], str]]


def start_daemon(settings: typing.Optional[typing.Dict] = None,
                 console_output: typing.Optional[bool] = True, verbose: typing.Optional[typing.List[str]] = None,
                 data_dir: typing.Optional[str] = None, wallet_dir: typing.Optional[str] = None,
                 download_dir: typing.Optional[str] = None):

    settings = settings or {}
    conf.initialize_settings(data_dir=data_dir, wallet_dir=wallet_dir, download_dir=download_dir)
    for k, v in settings.items():
        conf.settings.update({k, v}, data_types=(conf.TYPE_CLI,))

    log_support.configure_logging(conf.settings.get_log_filename(), console_output, verbose)
    log_support.configure_loggly_handler()
    log.debug('Final Settings: %s', conf.settings.get_current_settings_dict())
    log.info("Starting lbrynet-daemon from command line")

    if check_connection():
        daemon = Daemon()
        asyncio.get_event_loop().run_until_complete(daemon.start_listening())
        reactor.run()
    else:
        log.info("Not connected to internet, unable to start")


def start_daemon_with_cli_args(argv=None, data_dir: typing.Optional[str] = None,
                               wallet_dir: typing.Optional[str] = None, download_dir: typing.Optional[str] = None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--http-auth", dest="useauth", action="store_true", default=False
    )
    parser.add_argument(
        '--quiet', dest='quiet', action="store_true",
        help='Disable all console output.'
    )
    parser.add_argument(
        '--verbose', nargs="*",
        help=('Enable debug output. Optionally specify loggers for which debug output '
              'should selectively be applied.')
    )
    parser.add_argument(
        '--version', action="store_true",
        help='Show daemon version and quit'
    )

    args = parser.parse_args(argv)
    settings = {}
    if args.useauth:
        settings['use_auth_http'] = True

    verbose = None
    if args.verbose:
        verbose = args.verbose

    console_output = not args.quiet

    if args.version:
        print(json_dumps_pretty(get_platform()))
        return

    return start_daemon(settings, console_output, verbose, data_dir, wallet_dir, download_dir)


async def execute_command(method, params, data_dir: typing.Optional[str] = None,
                          wallet_dir: typing.Optional[str] = None, download_dir: typing.Optional[str] = None):
    # this check if the daemon is running or not
    conf.initialize_settings(data_dir=data_dir, wallet_dir=wallet_dir, download_dir=download_dir)
    api = None
    try:
        api = await LBRYAPIClient.get_client()
        await api.status()
    except (ClientConnectorError, ConnectionError):
        if api:
            await api.session.close()
        print("Could not connect to daemon. Are you sure it's running?")
        return 1

    # this actually executes the method
    resp = await api.call(method, params)

    try:
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
       lbrynet [--data_dir=<blob and database directory>] [--wallet_dir=<wallet directory>]
               [--download_dir=<downloads directory>] <command> [<args>]

    EXAMPLES
        lbrynet start                                # starts the daemon and listens for jsonrpc commands
        lbrynet help                                 # display this message
        lbrynet help <command_name>                  # get help for a command(doesn't need the daemon to be running)
        lbrynet commands                             # list available commands
        lbrynet status                               # get the running status of the daemon
        lbrynet resolve what                         # resolve a name

        lbrynet --wallet_dir=~/wallet2 start         # start the daemon using an alternative wallet directory
        lbrynet --data_dir=~/lbry start              # start the daemon using an alternative data directory

        lbrynet --data_dir=~/lbry <command_name>     # run a command on a daemon using an alternative data directory,
                                                     # which can contain a full daemon_settings.yml config file.
                                                     # Note: since the daemon is what runs the wallet and
                                                     # downloads files, only the --data_dir setting is needed when
                                                     # running commands. The wallet_dir and download_dir would only
                                                     # by used when starting the daemon.
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

    dir_args = {}
    if len(argv) >= 2:
        dir_arg_keys = [
            'data_dir',
            'wallet_dir',
            'download_directory'
        ]

        for arg in argv:
            found_dir_arg = False
            for key in dir_arg_keys:
                if arg.startswith(f'--{key}='):
                    if key in dir_args:
                        print(f"Multiple values provided for '{key}' argument")
                        print_help()
                        return 1
                    dir_args[key] = os.path.expanduser(os.path.expandvars(arg.lstrip(f'--{key}=')))
                    found_dir_arg = True
            if not found_dir_arg:
                break
        argv = argv[len(dir_args):]

    data_dir = dir_args.get('data_dir')
    wallet_dir = dir_args.get('wallet_dir')
    download_dir = dir_args.get('download_directory')

    for k, v in dir_args.items():
        if not os.path.isdir(v):
            print(f"'{data_dir}' is not a directory, cannot use it for {k}")
            return 1

    method, args = argv[0], argv[1:]

    if method in ['help', '--help', '-h']:
        if len(args) == 1:
            print_help_for_command(args[0])
        else:
            print_help()
        return 0

    elif method in ['version', '--version', '-v']:
        print("{lbrynet_name} {lbrynet_version}".format(
            lbrynet_name=lbrynet_name, **get_platform()
        ))
        return 0

    elif method == 'start':
        sys.exit(start_daemon_with_cli_args(args, data_dir, wallet_dir, download_dir))

    elif method == 'console':
        sys.exit(daemon_console())

    elif method not in Daemon.callable_methods:
        if method not in Daemon.deprecated_methods:
            print(f'{method} is not a valid command.')
            return 1

        new_method = Daemon.deprecated_methods[method].new_command
        if new_method is None:
            print(f"{method} is permanently deprecated and does not have a replacement command.")
            return 0

        print(f"{method} is deprecated, using {new_method}.")
        method = new_method

    fn = Daemon.callable_methods[method]
    parsed = docopt(fn.__doc__, args)
    params = set_kwargs(parsed)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(execute_command(method, params, data_dir, wallet_dir, download_dir))

    return 0


if __name__ == "__main__":
    sys.exit(main())
