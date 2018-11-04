import logging
import argparse
import asyncio
import aiohttp

from .node import Conductor, get_ledger_from_environment, get_blockchain_node_from_ledger
from .service import ConductorService


def get_argument_parser():
    parser = argparse.ArgumentParser(
        prog="torba"
    )
    subparsers = parser.add_subparsers(dest='command', help='sub-command help')

    subparsers.add_parser("gui", help="Start Qt GUI.")

    subparsers.add_parser("download", help="Download blockchain node binary.")

    start = subparsers.add_parser("start", help="Start orchstr8 service.")
    start.add_argument("--blockchain", help="Start blockchain node.", action="store_true")
    start.add_argument("--spv", help="Start SPV server.", action="store_true")
    start.add_argument("--wallet", help="Start wallet daemon.", action="store_true")

    generate = subparsers.add_parser("generate", help="Call generate method on running orchstr8 instance.")
    generate.add_argument("blocks", type=int, help="Number of blocks to generate")

    subparsers.add_parser("transfer", help="Call transfer method on running orchstr8 instance.")
    return parser


async def run_remote_command(command, **kwargs):
    async with aiohttp.ClientSession() as session:
        async with session.post('http://localhost:7954/'+command, data=kwargs) as resp:
            print(resp.status)
            print(await resp.text())


def main():
    parser = get_argument_parser()
    args = parser.parse_args()
    command = getattr(args, 'command', 'help')

    if command == 'gui':
        from torba.workbench import main as start_app  # pylint: disable=E0611,E0401
        return start_app()

    loop = asyncio.get_event_loop()
    ledger = get_ledger_from_environment()

    if command == 'download':
        logging.getLogger('blockchain').setLevel(logging.INFO)
        get_blockchain_node_from_ledger(ledger).ensure()

    elif command == 'generate':
        loop.run_until_complete(run_remote_command(
            'generate', blocks=args.blocks
        ))

    elif command == 'start':

        conductor = Conductor()
        if getattr(args, 'blockchain', False):
            loop.run_until_complete(conductor.start_blockchain())
        if getattr(args, 'spv', False):
            loop.run_until_complete(conductor.start_spv())
        if getattr(args, 'wallet', False):
            loop.run_until_complete(conductor.start_wallet())

        service = ConductorService(conductor, loop)
        loop.run_until_complete(service.start())

        try:
            print('========== Orchstr8 API Service Started ========')
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(service.stop())
            loop.run_until_complete(conductor.stop())

        loop.close()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
