import logging
import traceback
import argparse
import importlib
from torba.server.env import Env
from torba.server.server import Server


def get_argument_parser():
    parser = argparse.ArgumentParser(
        prog="torba-server"
    )
    parser.add_argument("spvserver", type=str, help="Python class path to SPV server implementation.")
    return parser


def get_coin_class(spvserver):
    spvserver_path, coin_class_name = spvserver.rsplit('.', 1)
    spvserver_module = importlib.import_module(spvserver_path)
    return getattr(spvserver_module, coin_class_name)


def main():
    parser = get_argument_parser()
    args = parser.parse_args()
    coin_class = get_coin_class(args.spvserver)
    logging.basicConfig(level=logging.INFO)
    logging.info('torba.server starting')
    try:
        server = Server(Env(coin_class))
        server.run()
    except Exception:
        traceback.print_exc()
        logging.critical('torba.server terminated abnormally')
    else:
        logging.info('torba.server terminated normally')


if __name__ == "__main__":
    main()
