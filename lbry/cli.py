import os
import sys
import asyncio
import pathlib
import argparse

from docopt import docopt

from lbry import __version__
from lbry.conf import Config, CLIConfig
from lbry.service import Daemon, Client
from lbry.service.metadata import interface
from lbry.service.full_node import FullNode
from lbry.blockchain.ledger import Ledger
from lbry.console import Advanced as AdvancedConsole, Basic as BasicConsole


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
                "Run 'lbrynet COMMAND --help' for more information on a command or group."
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
        self.exit(2, f"\n{message}\n")


class HelpFormatter(argparse.HelpFormatter):

    def add_usage(self, usage, actions, groups, prefix='Usage:  '):
        super().add_usage(
            usage, [a for a in actions if a.option_strings != ['--help']], groups, prefix
        )


def add_command_parser(parent, method_name, command):
    short = command['desc']['text'][0] if command['desc'] else ''
    subcommand = parent.add_parser(command['name'], help=short)
    subcommand.set_defaults(api_method_name=method_name, command=command['name'], doc=command['help'])


def get_argument_parser():
    root = ArgumentParser(
        'lbrynet', description='An interface to the LBRY Network.', allow_abbrev=False,
    )
    root.add_argument(
        '-v', '--version', dest='cli_version', action="store_true",
        help='Show lbrynet CLI version and exit.'
    )
    root.set_defaults(group=None, command=None)
    CLIConfig.contribute_to_argparse(root)
    sub = root.add_subparsers(metavar='COMMAND')
    start = sub.add_parser(
        'start',
        usage='lbrynet start [--config FILE] [--data-dir DIR] [--wallet-dir DIR] [--download-dir DIR] ...',
        help='Start LBRY Network interface.'
    )
    start.add_argument(
        '--full-node', dest='full_node', action="store_true",
        help='Start a full node with local blockchain data, requires lbrycrd.'
    )
    start.add_argument(
        '--quiet', dest='quiet', action="store_true",
        help='Disable all console output.'
    )
    start.add_argument(
        '--no-logging', dest='no_logging', action="store_true",
        help='Disable all logging of any kind.'
    )
    start.add_argument(
        '--verbose', nargs="*",
        help=('Enable debug output for lbry logger and event loop. Optionally specify loggers for which debug output '
              'should selectively be applied.')
    )
    start.add_argument(
        '--initial-headers', dest='initial_headers',
        help='Specify path to initial blockchain headers, faster than downloading them on first run.'
    )
    Config.contribute_to_argparse(start)
    start.set_defaults(command='start', start_parser=start, doc=start.format_help())

    groups = {}
    for group_name in sorted(interface['groups']):
        group_parser = sub.add_parser(group_name, group_name=group_name, help=interface['groups'][group_name])
        groups[group_name] = group_parser.add_subparsers(metavar='COMMAND')

    nicer_order = ['stop', 'get', 'publish', 'resolve']
    for command_name in sorted(interface['commands']):
        if command_name not in nicer_order:
            nicer_order.append(command_name)

    for command_name in nicer_order:
        command = interface['commands'][command_name]
        if command.get('group') is None:
            add_command_parser(sub, command_name, command)
        else:
            add_command_parser(groups[command['group']], command_name, command)

    return root


def ensure_directory_exists(path: str):
    if not os.path.isdir(path):
        pathlib.Path(path).mkdir(parents=True, exist_ok=True)


async def execute_command(conf, method, params):
    client = Client(f"http://{conf.api}/ws")
    await client.connect()
    resp = await client.send(method, **params)
    print(await resp.first)
    await client.disconnect()


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


def main(argv=None):
    argv = argv or sys.argv[1:]
    parser = get_argument_parser()
    args, command_args = parser.parse_known_args(argv)

    conf = Config.create_from_arguments(args)
    for directory in (conf.data_dir, conf.download_dir, conf.wallet_dir):
        ensure_directory_exists(directory)

    if args.cli_version:
        print(f"lbrynet {__version__}")
    elif args.command == 'start':
        if args.help:
            args.start_parser.print_help()
        elif args.full_node:
            print('Instantiating FullNode')
            service = FullNode(Ledger(conf))
            if conf.console == "advanced":
                console = AdvancedConsole(service)
            else:
                print('Instantiating BasicConsole')
                console = BasicConsole(service)
            print('Daemon(service, console).run()')
            return Daemon(service, console).run()
        else:
            print('Only `start --full-node` is currently supported.')
    elif args.command is not None:
        doc = args.doc
        api_method_name = args.api_method_name
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
