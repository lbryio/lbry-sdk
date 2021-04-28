import logging
import traceback
import argparse
import importlib
from lbry.wallet.server.env import Env
from lbry.wallet.server.server import Server


def get_argument_parser():
    parser = argparse.ArgumentParser(
        prog="lbry-hub"
    )
    parser.add_argument("spvserver", type=str, help="Python class path to SPV server implementation.",
                        nargs="?", default="lbry.wallet.server.coin.LBC")
    return parser


def get_coin_class(spvserver):
    spvserver_path, coin_class_name = spvserver.rsplit('.', 1)
    spvserver_module = importlib.import_module(spvserver_path)
    return getattr(spvserver_module, coin_class_name)


def main():
    parser = get_argument_parser()
    args = parser.parse_args()
    coin_class = get_coin_class(args.spvserver)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s %(name)s:%(lineno)d: %(message)s")
    logging.info('lbry.server starting')
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('elasticsearch').setLevel(logging.WARNING)
    try:
        server = Server(Env(coin_class))
        server.run()
    except Exception:
        traceback.print_exc()
        logging.critical('lbry.server terminated abnormally')
    else:
        logging.info('lbry.server terminated normally')


if __name__ == "__main__":
    main()
