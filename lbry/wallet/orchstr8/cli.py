import logging
import argparse
import asyncio
import aiohttp

from lbry import wallet
from lbry.wallet.orchstr8.node import (
    Conductor,
    get_lbcd_node_from_ledger,
    get_lbcwallet_node_from_ledger
)
from lbry.wallet.orchstr8.service import ConductorService


def get_argument_parser():
    parser = argparse.ArgumentParser(
        prog="orchstr8"
    )
    subparsers = parser.add_subparsers(dest='command', help='sub-command help')

    subparsers.add_parser("download", help="Download lbcd and lbcwallet node binaries.")

    start = subparsers.add_parser("start", help="Start orchstr8 service.")
    start.add_argument("--lbcd", help="Hostname to start lbcd node.")
    start.add_argument("--lbcwallet", help="Hostname to start lbcwallet node.")
    start.add_argument("--spv", help="Hostname to start SPV server.")
    start.add_argument("--wallet", help="Hostname to start wallet daemon.")

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

    loop = asyncio.get_event_loop()
    asyncio.set_event_loop(loop)

    if command == 'download':
        logging.getLogger('blockchain').setLevel(logging.INFO)
        get_lbcd_node_from_ledger(wallet).ensure()
        get_lbcwallet_node_from_ledger(wallet).ensure()

    elif command == 'generate':
        loop.run_until_complete(run_remote_command(
            'generate', blocks=args.blocks
        ))

    elif command == 'start':

        conductor = Conductor()
        if getattr(args, 'lbcd', False):
            conductor.lbcd_node.hostname = args.lbcd
            loop.run_until_complete(conductor.start_lbcd())
        if getattr(args, 'lbcwallet', False):
            conductor.lbcwallet_node.hostname = args.lbcwallet
            loop.run_until_complete(conductor.start_lbcwallet())
        if getattr(args, 'spv', False):
            conductor.spv_node.hostname = args.spv
            loop.run_until_complete(conductor.start_spv())
        if getattr(args, 'wallet', False):
            conductor.wallet_node.hostname = args.wallet
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
