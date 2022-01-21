import logging
import traceback
import argparse
from lbry.wallet.server.env import Env
from lbry.wallet.server.block_processor import BlockProcessor
from lbry.wallet.server.chain_reader import BlockchainReaderServer
from lbry.wallet.server.db.elasticsearch.sync import ElasticWriter


def get_args_and_setup_logging(name):
    parser = argparse.ArgumentParser(
        prog=name
    )
    Env.contribute_to_arg_parser(parser)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s %(name)s:%(lineno)d: %(message)s")
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('elasticsearch').setLevel(logging.WARNING)
    return args


def run_writer_forever():
    args = get_args_and_setup_logging('lbry-hub-writer')
    try:
        block_processor = BlockProcessor(Env.from_arg_parser(args))
        block_processor.run()
    except Exception:
        traceback.print_exc()
        logging.critical('block processor terminated abnormally')
    else:
        logging.info('block processor terminated normally')


def run_server_forever():
    args = get_args_and_setup_logging('lbry-hub-server')

    try:
        server = BlockchainReaderServer(Env.from_arg_parser(args))
        server.run()
    except Exception:
        traceback.print_exc()
        logging.critical('server terminated abnormally')
    else:
        logging.info('server terminated normally')


def run_es_sync_forever():
    args = get_args_and_setup_logging('lbry-hub-elastic-sync')
    try:
        server = ElasticWriter(Env.from_arg_parser(args))
        server.run()
    except Exception:
        traceback.print_exc()
        logging.critical('es writer terminated abnormally')
    else:
        logging.info('es writer terminated normally')
