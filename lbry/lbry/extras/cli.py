import os
import sys
import signal
import pathlib
import json
import asyncio
import argparse
import logging
import logging.handlers
import typing
from docopt import docopt

import aiohttp
from aiohttp.web import GracefulExit

from lbry import __version__ as lbrynet_version
from lbry.extras.daemon.loggly_handler import get_loggly_handler
from lbry.conf import Config, CLIConfig
from lbry.extras.daemon.Daemon import Daemon

log = logging.getLogger('lbry')
log.addHandler(logging.NullHandler())


async def _task_decorator(coro: typing.Coroutine):
    try:
        return await coro
    except asyncio.CancelledError:
        raise
    except BaseException as e:
        log.exception('unhandled error in task')
        raise e


def task_factory(loop: asyncio.AbstractEventLoop, coro: typing.Coroutine):
    task = asyncio.tasks.Task(_task_decorator(coro), loop=loop)
    if task._source_traceback:
        del task._source_traceback[-1]
    return task


def display(data):
    print(json.dumps(data, indent=2))


async def execute_command(conf, method, params, callback=display):
    async with aiohttp.ClientSession() as session:
        try:
            message = {'method': method, 'params': params}
            async with session.get(conf.api_connection_url, json=message) as resp:
                try:
                    data = await resp.json()
                    if 'result' in data:
                        return callback(data['result'])
                    elif 'error' in data:
                        return callback(data['error'])
                except Exception as e:
                    log.exception('Could not process response from server:', exc_info=e)
        except aiohttp.ClientConnectionError:
            print("Could not connect to daemon. Are you sure it's running?")


def normalize_value(x, key=None):
    if not isinstance(x, str):
        return x
    if key in ('uri', 'channel_name', 'name', 'file_name', 'claim_name', 'download_directory'):
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
        if arg is None:
            continue
        k = None
        if key.startswith("--") and remove_brackets(key[2:]) not in kwargs:
            k = remove_brackets(key[2:])
        elif remove_brackets(key) not in kwargs:
            k = remove_brackets(key)
        kwargs[k] = normalize_value(arg, k)
    return kwargs


def split_subparser_argument(parent, original, name, condition):
    new_sub_parser = argparse._SubParsersAction(
        original.option_strings,
        original._prog_prefix,
        original._parser_class,
        metavar=original.metavar
    )
    new_sub_parser._name_parser_map = original._name_parser_map
    new_sub_parser._choices_actions = [
        a for a in original._choices_actions if condition(original._name_parser_map[a.dest])
    ]
    group = argparse._ArgumentGroup(parent, name)
    group._group_actions = [new_sub_parser]
    return group


class ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, group_name=None, **kwargs):
        super().__init__(*args, formatter_class=HelpFormatter, add_help=False, **kwargs)
        self.add_argument(
            '--help', dest='help', action='store_true', default=False,
            help='Show this help message and exit.'
        )
        self._optionals.title = 'Options'
        if group_name is None:
            self.epilog = (
                f"Run 'lbrynet COMMAND --help' for more information on a command or group."
            )
        else:
            self.epilog = (
                f"Run 'lbrynet {group_name} COMMAND --help' for more information on a command."
            )
            self.set_defaults(group=group_name, group_parser=self)

    def format_help(self):
        formatter = self._get_formatter()
        formatter.add_usage(
            self.usage, self._actions, self._mutually_exclusive_groups
        )
        formatter.add_text(self.description)

        # positionals, optionals and user-defined groups
        for action_group in self._granular_action_groups:
            formatter.start_section(action_group.title)
            formatter.add_text(action_group.description)
            formatter.add_arguments(action_group._group_actions)
            formatter.end_section()

        formatter.add_text(self.epilog)
        return formatter.format_help()

    @property
    def _granular_action_groups(self):
        if self.prog != 'lbrynet':
            yield from self._action_groups
            return
        yield self._optionals
        action: argparse._SubParsersAction = self._positionals._group_actions[0]
        yield split_subparser_argument(
            self, action, "Grouped Commands", lambda parser: 'group' in parser._defaults
        )
        yield split_subparser_argument(
            self, action, "Commands", lambda parser: 'group' not in parser._defaults
        )

    def error(self, message):
        self.print_help(argparse._sys.stderr)
        self.exit(2, '\n'+message+'\n')


class HelpFormatter(argparse.HelpFormatter):

    def add_usage(self, usage, actions, groups, prefix='Usage:  '):
        super().add_usage(
            usage, [a for a in actions if a.option_strings != ['--help']], groups, prefix
        )


def add_command_parser(parent, command):
    subcommand = parent.add_parser(
        command['name'],
        help=command['doc'].strip().splitlines()[0]
    )
    subcommand.set_defaults(
        api_method_name=command['api_method_name'],
        command=command['name'],
        doc=command['doc'],
        replaced_by=command.get('replaced_by', None)
    )


def get_argument_parser():
    main = ArgumentParser(
        'lbrynet', description='An interface to the LBRY Network.', allow_abbrev=False,
    )
    main.add_argument(
        '-v', '--version', dest='cli_version', action="store_true",
        help='Show lbrynet CLI version and exit.'
    )
    main.set_defaults(group=None, command=None)
    CLIConfig.contribute_to_argparse(main)
    sub = main.add_subparsers(metavar='COMMAND')
    start = sub.add_parser(
        'start',
        usage='lbrynet start [--config FILE] [--data-dir DIR] [--wallet-dir DIR] [--download-dir DIR] ...',
        help='Start LBRY Network interface.'
    )
    start.add_argument(
        '--quiet', dest='quiet', action="store_true",
        help='Disable all console output.'
    )
    start.add_argument(
        '--verbose', nargs="*",
        help=('Enable debug output. Optionally specify loggers for which debug output '
              'should selectively be applied.')
    )
    Config.contribute_to_argparse(start)
    start.set_defaults(command='start', start_parser=start, doc=start.format_help())

    api = Daemon.get_api_definitions()
    groups = {}
    for group_name in sorted(api['groups']):
        group_parser = sub.add_parser(group_name, group_name=group_name, help=api['groups'][group_name])
        groups[group_name] = group_parser.add_subparsers(metavar='COMMAND')

    nicer_order = ['stop', 'get', 'publish', 'resolve']
    for command_name in sorted(api['commands']):
        if command_name not in nicer_order:
            nicer_order.append(command_name)

    for command_name in nicer_order:
        command = api['commands'][command_name]
        if command['group'] is None:
            add_command_parser(sub, command)
        else:
            add_command_parser(groups[command['group']], command)

    return main


def ensure_directory_exists(path: str):
    if not os.path.isdir(path):
        pathlib.Path(path).mkdir(parents=True, exist_ok=True)


def run_daemon(args: list, conf: Config):
    default_formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s:%(lineno)d: %(message)s")
    file_handler = logging.handlers.RotatingFileHandler(
        conf.log_file_path, maxBytes=2097152, backupCount=5
    )
    file_handler.setFormatter(default_formatter)
    log.addHandler(file_handler)
    logging.getLogger('torba').addHandler(file_handler)

    if not args.quiet:
        handler = logging.StreamHandler()
        handler.setFormatter(default_formatter)
        log.addHandler(handler)
        logging.getLogger('torba').addHandler(handler)
        logging.getLogger('torba').setLevel(logging.INFO)

    logging.getLogger('aioupnp').setLevel(logging.WARNING)
    logging.getLogger('aiohttp').setLevel(logging.CRITICAL)

    loop = asyncio.get_event_loop()
    loop.set_task_factory(task_factory)

    if args.verbose:
        log.setLevel(logging.DEBUG)
        loop.set_debug(True)
    else:
        log.setLevel(logging.INFO)

    if conf.share_usage_data:
        loggly_handler = get_loggly_handler()
        loggly_handler.setLevel(logging.ERROR)
        log.addHandler(loggly_handler)

    daemon = Daemon(conf)

    def __exit():
        raise GracefulExit()

    try:
        loop.add_signal_handler(signal.SIGINT, __exit)
        loop.add_signal_handler(signal.SIGTERM, __exit)
    except NotImplementedError:
        pass  # Not implemented on Windows

    try:
        loop.run_until_complete(daemon.start())
        loop.run_forever()
    except (GracefulExit, KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        loop.run_until_complete(daemon.stop())

    if hasattr(loop, 'shutdown_asyncgens'):
        loop.run_until_complete(loop.shutdown_asyncgens())


def main(argv=None):
    argv = argv or sys.argv[1:]
    parser = get_argument_parser()
    args, command_args = parser.parse_known_args(argv)

    conf = Config.create_from_arguments(args)
    for directory in (conf.data_dir, conf.download_dir, conf.wallet_dir):
        ensure_directory_exists(directory)

    if args.cli_version:
        print(f"lbrynet {lbrynet_version}")
    elif args.command == 'start':
        if args.help:
            args.start_parser.print_help()
        else:
            run_daemon(args, conf)
    elif args.command is not None:
        doc = args.doc
        api_method_name = args.api_method_name
        if args.replaced_by:
            print(f"{args.api_method_name} is deprecated, using {args.replaced_by['api_method_name']}.")
            doc = args.replaced_by['doc']
            api_method_name = args.replaced_by['api_method_name']
        if args.help:
            print(doc)
        else:
            parsed = docopt(doc, command_args)
            params = set_kwargs(parsed)
            asyncio.get_event_loop().run_until_complete(execute_command(conf, api_method_name, params))
    elif args.group is not None:
        args.group_parser.print_help()
    else:
        parser.print_help()

    return 0


if __name__ == "__main__":
    sys.exit(main())
