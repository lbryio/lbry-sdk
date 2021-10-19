import logging
import traceback
import argparse
from lbry.wallet.server.env import Env
from lbry.wallet.server.server import Server


def get_argument_parser():
    parser = argparse.ArgumentParser(
        prog="lbry-hub"
    )
    Env.contribute_to_arg_parser(parser)
    sub = parser.add_subparsers(metavar='COMMAND')
    start = sub.add_parser('start', help='Start LBRY Network interface.')

    return parser


def main():
    parser = get_argument_parser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s %(name)s:%(lineno)d: %(message)s")
    logging.info('lbry.server starting')
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('elasticsearch').setLevel(logging.WARNING)
    try:
        server = Server(Env.from_arg_parser(args))
        server.run()
    except Exception:
        traceback.print_exc()
        logging.critical('lbry.server terminated abnormally')
    else:
        logging.info('lbry.server terminated normally')


if __name__ == "__main__":
    main()
