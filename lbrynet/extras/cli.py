import sys
import json
import asyncio
import argparse
import logging
from docopt import docopt
from textwrap import dedent

import aiohttp
from lbrynet.extras.compat import force_asyncioreactor_install
force_asyncioreactor_install()

from lbrynet import log_support, __name__ as lbrynet_name, __version__ as lbrynet_version
from lbrynet.extras.daemon.loggly_handler import get_loggly_handler
from lbrynet.conf import Config, CLIConfig
from lbrynet.utils import check_connection
from lbrynet.extras.daemon.Daemon import Daemon

log = logging.getLogger(lbrynet_name)
log.addHandler(logging.NullHandler())


def display(data):
    print(json.dumps(data["result"], indent=2))


async def execute_command(conf, method, params):
    async with aiohttp.ClientSession() as session:
        try:
            message = {'method': method, 'params': params}
            async with session.get(conf.api_connection_url, json=message) as resp:
                try:
                    data = await resp.json()
                    if 'result' in data:
                        display(data['result'])
                    elif 'error' in data:
                        if 'message' in data['error']:
                            display(data['error']['message'])
                        else:
                            display(data['error'])
                except Exception as e:
                    log.exception('Could not process response from server:', exc_info=e)
        except aiohttp.ClientConnectionError:
            print("Could not connect to daemon. Are you sure it's running?")


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
    main = argparse.ArgumentParser('lbrynet')
    main.add_argument(
        '--version', dest='cli_version', action="store_true",
        help='Show lbrynet CLI version and exit.'
    )
    CLIConfig.contribute_args(main)
    sub = main.add_subparsers(dest='command')
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
    start.add_argument(
        '--version', action="store_true",
        help='Show daemon version and quit'
    )
    Config.contribute_args(start)
    api = Daemon.get_api_definitions()
    for group in sorted(api):
        group_command = sub.add_parser(group, help=api[group]['doc'])
        group_command.set_defaults(group_doc=group_command)
        commands = group_command.add_subparsers(dest='subcommand')
        for command in api[group]['commands']:
            commands.add_parser(command['name'], help=command['doc'].strip().splitlines()[0])
    return main


def main(argv=None):
    argv = argv or sys.argv[1:]
    parser = get_argument_parser()
    args = parser.parse_args(argv)

    conf = Config()

    if args.cli_version:
        print(f"{lbrynet_name} {lbrynet_version}")
        return 0

    elif args.command == 'start':
        console_output = True
        verbose = True

        log_support.configure_logging(conf.log_file_path, console_output, verbose)

        if conf.share_usage_data:
            loggly_handler = get_loggly_handler()
            loggly_handler.setLevel(logging.ERROR)
            log.addHandler(loggly_handler)

        log.debug('Final Settings: %s', conf.settings_dict)
        log.info("Starting lbrynet-daemon from command line")

        daemon = Daemon(conf)

        if check_connection():
            from twisted.internet import reactor
            reactor._asyncioEventloop.create_task(daemon.start())
            reactor.run()
        else:
            log.info("Not connected to internet, unable to start")

    elif args.command is not None:

        if args.subcommand is None:
            args.group_doc.print_help()

        else:
            method = f'{args.command}_{args.subcommand}'
            fn = Daemon.callable_methods[method]
            parsed = docopt(fn.__doc__, [method]+argv[2:])
            params = set_kwargs(parsed)
            loop = asyncio.get_event_loop()
            loop.run_until_complete(execute_command(conf, method, params))

    else:
        parser.print_help()

    return 0


if __name__ == "__main__":
    sys.exit(main())
