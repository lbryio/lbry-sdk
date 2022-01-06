import logging
import traceback
import argparse
from lbry.wallet.server.env import Env
from lbry.wallet.server.block_processor import BlockProcessor
from lbry.wallet.server.chain_reader import BlockchainReaderServer


def get_argument_parser():
    parser = argparse.ArgumentParser(
        prog="lbry-hub"
    )
    Env.contribute_to_arg_parser(parser)
    return parser


def main():
    parser = get_argument_parser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s %(name)s:%(lineno)d: %(message)s")
    logging.info('lbry.server starting')
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('elasticsearch').setLevel(logging.WARNING)

    if args.es_mode == 'writer':
        try:
            block_processor = BlockProcessor(Env.from_arg_parser(args))
            block_processor.run()
        except Exception:
            traceback.print_exc()
            logging.critical('block processor terminated abnormally')
        else:
            logging.info('block processor terminated normally')
    else:
        try:
            server = BlockchainReaderServer(Env.from_arg_parser(args))
            server.run()
        except Exception:
            traceback.print_exc()
            logging.critical('server terminated abnormally')
        else:
            logging.info('server terminated normally')


if __name__ == "__main__":
    main()
