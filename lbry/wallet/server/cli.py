import logging
import traceback
import argparse
from lbry.wallet.server.env import Env
from lbry.wallet.server.block_processor import BlockProcessor
from lbry.wallet.server.chain_reader import BlockchainReaderServer
from lbry.wallet.server.db.elasticsearch.sync import ElasticWriter


def get_arg_parser(name):
    parser = argparse.ArgumentParser(
        prog=name
    )
    Env.contribute_to_arg_parser(parser)
    return parser


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s %(name)s:%(lineno)d: %(message)s")
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('elasticsearch').setLevel(logging.WARNING)


def run_writer_forever():
    setup_logging()
    args = get_arg_parser('lbry-hub-writer').parse_args()
    try:
        block_processor = BlockProcessor(Env.from_arg_parser(args))
        block_processor.run()
    except Exception:
        traceback.print_exc()
        logging.critical('block processor terminated abnormally')
    else:
        logging.info('block processor terminated normally')


def run_server_forever():
    setup_logging()
    args = get_arg_parser('lbry-hub-server').parse_args()

    try:
        server = BlockchainReaderServer(Env.from_arg_parser(args))
        server.run()
    except Exception:
        traceback.print_exc()
        logging.critical('server terminated abnormally')
    else:
        logging.info('server terminated normally')


def run_es_sync_forever():
    setup_logging()
    parser = get_arg_parser('lbry-hub-elastic-sync')
    parser.add_argument('--reindex', type=bool, default=False)
    args = parser.parse_args()

    try:
        server = ElasticWriter(Env.from_arg_parser(args))
        server.run(args.reindex)
    except Exception:
        traceback.print_exc()
        logging.critical('es writer terminated abnormally')
    else:
        logging.info('es writer terminated normally')
