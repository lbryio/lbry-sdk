import asyncio
import struct
from binascii import hexlify
from multiprocessing.queues import Queue

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk

from lbry.wallet.constants import CLAIM_TYPE_NAMES


async def indexer_task(claim_queue: Queue, index='claims'):
    es = AsyncElasticsearch()
    try:
        await consume(es, claim_queue, index)
    finally:
        await es.close()


async def consume(es, claim_queue, index):
    to_send = []
    while True:
        if not claim_queue.empty():
            operation, doc = claim_queue.get_nowait()
            if operation == 'delete':
                to_send.append({'_index': index, '_op_type': 'delete', '_id': hexlify(doc[::-1]).decode()})
                continue
            try:
                to_send.append(extract_doc(doc, index))
            except OSError as e:
                print(e)
        else:
            if to_send:
                print(await async_bulk(es, to_send, raise_on_error=False))
                to_send.clear()
            else:
                await asyncio.sleep(.1)


def extract_doc(doc, index):
    doc['claim_id'] = hexlify(doc.pop('claim_hash')[::-1]).decode()
    if doc['reposted_claim_hash'] is not None:
        doc['reposted_claim_id'] = hexlify(doc.pop('reposted_claim_hash')[::-1]).decode()
    else:
        doc['reposted_claim_hash'] = None
    channel_hash = doc.pop('channel_hash')
    doc['channel_id'] = hexlify(channel_hash[::-1]).decode() if channel_hash else channel_hash
    txo_hash = doc.pop('txo_hash')
    doc['tx_id'] = hexlify(txo_hash[:32][::-1]).decode()
    doc['tx_nout'] = struct.unpack('<I', txo_hash[32:])[0]
    doc['is_controlling'] = bool(doc['is_controlling'])
    doc['signature'] = hexlify(doc.pop('signature') or b'').decode() or None
    doc['signature_digest'] = hexlify(doc.pop('signature_digest') or b'').decode() or None
    doc['public_key_bytes'] = hexlify(doc.pop('public_key_bytes') or b'').decode() or None
    doc['public_key_hash'] = hexlify(doc.pop('public_key_hash') or b'').decode() or None
    doc['signature_valid'] = bool(doc['signature_valid'])
    if doc['claim_type'] is None:
        doc['claim_type'] = 'invalid'
    else:
        doc['claim_type'] = CLAIM_TYPE_NAMES[doc['claim_type']]
    return {'doc': doc, '_id': doc['claim_id'], '_index': index, '_op_type': 'update',
           'doc_as_upsert': True}
