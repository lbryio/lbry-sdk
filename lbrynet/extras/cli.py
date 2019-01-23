import sys
import json
import asyncio
import argparse
import typing
import logging.handlers
import aiohttp
from docopt import docopt
from textwrap import dedent

from lbrynet import __name__ as lbrynet_name, __version__ as lbrynet_version
from lbrynet.conf import Config, CLIConfig
from lbrynet.extras.daemon.Daemon import Daemon
from lbrynet.extras.daemon.client import LBRYAPIClient, JSONRPCException
from lbrynet.extras.daemon.loggly_handler import get_loggly_handler

log = logging.getLogger(lbrynet_name)
log.addHandler(logging.NullHandler())
default_formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s:%(lineno)d: %(message)s")

optional_path_getter_type = typing.Optional[typing.Callable[[], str]]


async def start_daemon(conf: Config, args):
    file_handler = logging.handlers.RotatingFileHandler(conf.log_file_path,
                                                        maxBytes=2097152, backupCount=5)
    file_handler.setFormatter(default_formatter)
    log.addHandler(file_handler)

    if not args.quiet:
        handler = logging.StreamHandler()
        handler.setFormatter(default_formatter)
        log.addHandler(handler)

    # mostly disable third part logging
    logging.getLogger('urllib3').setLevel(logging.CRITICAL)
    logging.getLogger('BitcoinRPC').setLevel(logging.INFO)
    logging.getLogger('aioupnp').setLevel(logging.WARNING)
    logging.getLogger('aiohttp').setLevel(logging.CRITICAL)

    if args.verbose:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)

    if conf.share_usage_data:
        loggly_handler = get_loggly_handler()
        loggly_handler.setLevel(logging.ERROR)
        log.addHandler(loggly_handler)

    log.info("Starting lbrynet-daemon from command line")
    daemon = Daemon(conf)
    try:
        await daemon.start_listening()
    except (OSError, asyncio.CancelledError):
        return 1
    try:
        await daemon.server.wait_closed()
    except (KeyboardInterrupt, asyncio.CancelledError):
        await daemon.shutdown()
    return 0


def display(data):
    print(json.dumps(data, indent=2))


async def execute_command(conf, method, params):
    client = LBRYAPIClient(conf)
    try:
        result = await getattr(client, method)(params)
        print(display(result))
    except aiohttp.ClientConnectionError:
        print("Could not connect to daemon. Are you sure it's running?")
    except JSONRPCException as err:
        print(err)


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


def get_argument_parser():
    main = argparse.ArgumentParser('lbrynet', add_help=False)
    main.add_argument(
        '--version', dest='cli_version', action="store_true",
        help='Show lbrynet CLI version and exit.'
    )
    main.add_argument(
        '-h', '--help', dest='help', action="store_true",
        help='Show this help message and exit'
    )
    CLIConfig.contribute_args(main)
    sub = main.add_subparsers(dest='command')
    help = sub.add_parser('help', help='Detailed help for remote commands.')
    help.add_argument('help_command', nargs='*')
    start = sub.add_parser('start', help='Start lbrynet server.')
    start.add_argument(
        '--quiet', dest='quiet', action="store_true",
        help='Disable all console output.'
    )
    start.add_argument(
        '--verbose', nargs="*",
        help=('Enable debug output. Optionally specify loggers for which debug output '
              'should selectively be applied.')
    )
    Config.contribute_args(start)
    api = Daemon.get_api_definitions()
    for group in sorted(api):
        group_command = sub.add_parser(group, help=api[group]['doc'])
        group_command.set_defaults(group_doc=group_command)
        if group in ('status', 'publish', 'version', 'help', 'wallet_balance', 'get'):
            continue
        commands = group_command.add_subparsers(dest='subcommand')
        for command in api[group]['commands']:
            commands.add_parser(command['name'], help=command['doc'].strip().splitlines()[0])
    for deprecated in Daemon.deprecated_methods:
        group_command = sub.add_parser(deprecated)
        group_command.add_subparsers(dest='subcommand')
    return main


def main(argv=None):
    argv = argv or sys.argv[1:]
    parser = get_argument_parser()
    args, command_args = parser.parse_known_args(argv)
    conf = Config.create_from_arguments(args)

    if args.cli_version:
        print(f"{lbrynet_name} {lbrynet_version}")
        return 0
    elif args.command == 'start':
        asyncio.run(start_daemon(conf, args))
    elif args.command == 'help':
        if args.help_command:
            method = '_'.join(args.help_command)
        else:
            parser.print_help()
            return 0
        if method not in Daemon.callable_methods:
            print('Invalid command name: {method}')
            return 1

        fn = Daemon.callable_methods[method]
        print(fn.__doc__)

    elif args.command is not None:
        if args.command in ('status', 'publish', 'version', 'help', 'wallet_balance', 'get'):
            method = args.command
        elif args.subcommand is not None:
            method = f'{args.command}_{args.subcommand}'
        else:
            args.group_doc.print_help()
            return 0

        if method in Daemon.deprecated_methods:
            new_method = Daemon.deprecated_methods[method].new_command
            if new_method is None:
                print(f"{method} is permanently deprecated and does not have a replacement command.")
                return 0
            print(f"{method} is deprecated, using {new_method}.")
            method = new_method

        fn = Daemon.callable_methods[method]
        parsed = docopt(fn.__doc__, args)
        params = set_kwargs(parsed)
        asyncio.run(execute_command(conf, method, params))
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
