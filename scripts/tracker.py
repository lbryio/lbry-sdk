#!/usr/bin/env python

import asyncio
import json
import logging
import pickle
import signal
import sqlite3
import time
from os import path
from pprint import pprint
from urllib.parse import unquote

from aioupnp import upnp, fault as upnpfault
from aiohttp import web

from lbry.wallet.network import ClientSession
from lbry.schema.result import Outputs
from lbry.wallet.transaction import Transaction
from binascii import hexlify, unhexlify
from lbry.dht import node, peer

log = logging.getLogger("lbry")
log.addHandler(logging.StreamHandler())
log.setLevel(logging.INFO)


async def main():
    data_dir = "/home/grin/code/lbry/sdk"
    state_dir = data_dir + '/nodestate/'
    loop = asyncio.get_event_loop()

    try:
        loop.add_signal_handler(signal.SIGINT, shutdown)
        loop.add_signal_handler(signal.SIGTERM, shutdown)
    except NotImplementedError:
        pass  # Not implemented on Windows

    db = sqlite3.connect(data_dir + "/tracker.sqlite3")
    db.execute('CREATE TABLE IF NOT EXISTS announce (local_id TEXT, hash TEXT, node_id TEXT, ip TEXT, port INT, timestamp INT)')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS node_id_hash_idx ON announce (node_id, hash)')

    spv_host = 'spv13.lbry.com'
    wallet_client = ClientSession(network=None, server=(spv_host, 50001))
    await wallet_client.create_connection()

    asyncio.create_task(run_web_api(loop, db, wallet_client))

    num_nodes = 128
    u = await upnp.UPnP.discover()
    external_ip = await u.get_external_ip()

    try:
        nodes = await start_nodes(loop, num_nodes, external_ip, state_dir)

        await asyncio.gather(*map(lambda n: n.started_listening.wait(), nodes), loop=loop)
        print("joined")

        queue = asyncio.Queue(maxsize=100*num_nodes)
        for n in nodes:
            asyncio.create_task(drain_events(n, queue))

        while True:
            (n, node_id, ip, method, args) = await queue.get()
            local_node_id = bytes.hex(n.protocol.node_id)
            if method != b'store':
                # print(f"{local_node_id[:8]}: {method} from {bytes.hex(node_id)} ({ip})")
                continue

            if len(args)< 5:
                print(f'malformed args to Store')
                pprint(args)
                continue

            blob_hash, token, port, original_publisher_id, age = args[:5]
            print(f"STORE to {local_node_id[:8]} from {bytes.hex(node_id)[:8]} ({ip}) for blob {bytes.hex(blob_hash)[:8]}")

            try:
                cur = db.cursor()
                cur.execute(
                    '''
                    INSERT INTO announce (local_id, hash, node_id, ip, port, timestamp) VALUES (?,?,?,?,?,?)
                    ON CONFLICT (node_id, hash) DO UPDATE SET 
                    local_id=excluded.local_id, ip=excluded.ip, port=excluded.port, timestamp=excluded.timestamp
                    ''',
                    (local_node_id, bytes.hex(blob_hash), bytes.hex(node_id), ip, port, int(time.time()))
                )
                db.commit()
                cur.close()
            except sqlite3.Error as err:
                print("failed sqlite insert", err)
    finally:
        print("shutting down")
        for n in nodes:
            node_id = bytes.hex(n.protocol.node_id)
            n.stop()
            # print(f'deleting upnp port mapping {n.protocol.udp_port}')
            try:
                await u.delete_port_mapping(n.protocol.udp_port, "UDP")
            except upnpfault.UPnPError:
                pass

            state = n.get_state()
            # keep existing rt if there is one
            if len(state.routing_table_peers) == 0 and path.exists(state_dir + node_id):
                with open(state_dir + node_id, 'rb') as f:
                    existing_state = pickle.load(f)
                    if len(existing_state.routing_table_peers) > 0:
                        state.routing_table_peers = existing_state.routing_table_peers
                        print(f'rt empty on save, but old rt was recovered ({len(state.routing_table_peers)} peers)')
            with open(state_dir + node_id, 'wb') as f:
                # pprint(state.routing_table_peers)
                # pprint(state.datastore)
                print(f'{node_id[:8]}: saved {len(state.routing_table_peers)} rt peers, {len(state.datastore)} in store')
                pickle.dump(state, f)
        await wallet_client.close()
        db.close()


class ShutdownErr(BaseException):
    pass


def shutdown():
    print("got interrupt signal...")
    raise ShutdownErr()


def make_node_id(i: int, n: int) -> str:
    """
    split dht address space into N chunks and return the first id of the i'th chunk
    make_node_id(0,n) returns 000...000 for any n
    """
    if not 0 <= i < n:
        raise ValueError("i must be between 0 (inclusive) and n (exclusive)")
    bytes_in_id = 48
    return "{0:0{1}x}".format(i * ((2**8)**bytes_in_id // n), bytes_in_id*2)


async def start_nodes(loop, num_nodes, external_ip, state_dir):
    start_port = 4445
    known_node_urls = [("lbrynet1.lbry.com", 4444), ("lbrynet2.lbry.com", 4444), ("lbrynet3.lbry.com", 4444)]
    peer_manager = peer.PeerManager(loop)

    nodes = []
    for i in range(num_nodes):
        node_id = make_node_id(i, num_nodes)
        # pprint(node_id)

        port = start_port + i
        # await u.get_next_mapping(port, "UDP", "lbry dht tracker") # not necessary, i just opened ports in router

        n = node.Node(loop, peer_manager, node_id=bytes.fromhex(node_id), external_ip=external_ip,
                      udp_port=port, internal_udp_port=port, peer_port=3333)

        persisted_peers = []
        if path.exists(state_dir + node_id):
            with open(state_dir + node_id, 'rb') as f:
                state = pickle.load(f)
                # pprint(state.routing_table_peers)
                # pprint(state.datastore)
                print(f'{node_id[:8]}: loaded {len(state.routing_table_peers)} rt peers, {len(state.datastore)} in store')
                n.load_state(state)
                persisted_peers = state.routing_table_peers
                # if len(persisted_peers) == 0 and len(state.datastore) > 0:
                #     peers_to_import = map(lambda p: (p[0], p[1], p[2], p[3]), n.get_state().datastore)
                #     persisted_peers.extend(peers_to_import)
                #     print(f'{node_id[:8]}: rt is empty but we recovered {len(state.datastore)} '
                #           f'peers from the datastore. {len(peers_to_import)} of those were recent enough to import')

        n.start("0.0.0.0", known_node_urls, persisted_peers)
        nodes.append(n)
    return nodes


async def drain_events(n, q):
    # print(f'drain started on {bytes.hex(n.protocol.node_id)[:8]}')
    while True:
        (node_id, ip, method, args) = await n.protocol.event_queue.get()
        try:
            q.put_nowait((n, node_id, ip, method, args))
        except asyncio.QueueFull:
            pass


async def run_web_api(loop, db, wallet_client):
    try:
        app = web.Application(loop=loop)
        app['db'] = db
        app['wallet_client'] = wallet_client
        app.add_routes([
            web.get('/', api_handler),
            web.get('/seeds/hash/{hash}', seeds_handler),
            web.get('/seeds/url/{url}', url_handler),
        ])
        # server = web.Server(api_handler, loop=loop)
        # runner = web.ServerRunner(server)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', 8080)
        await site.start()
    except Exception as err:
        pprint(err)
        await runner.cleanup()


async def seeds_handler(request):
    blobhash = request.match_info['hash']
    db = request.app['db']
    try:
        cur = db.cursor()
        c = cur.execute("""
            select count(distinct(node_id)) from announce where hash = ? and timestamp > strftime('%s','now','-1 day')
        """, (blobhash,)).fetchone()[0]
        cur.close()
        return web.Response(text=json.dumps({'seeds': c})+"\n")
    except Exception as err:
        return web.Response(text=json.dumps({'error': err})+"\n")


async def url_handler(request):
    url = unquote(request.match_info['url'])
    log.warning(url)
    db = request.app['db']
    wallet_client = request.app['wallet_client']

    try:
        sd_hash = await get_sd_hash(wallet_client, url)
        if sd_hash is None:
            return web.Response(text=json.dumps({'error': 'Could not get sd hash for url', 'url': url})+"\n")
        seeds = get_seeds(db, sd_hash)
        return web.Response(text=json.dumps({'url': url, 'sd_hash': sd_hash, 'seeds': seeds})+"\n")
    except Exception as err:
        return web.Response(text=json.dumps({'error': err})+"\n")


def get_seeds(db, blobhash):
    cur = db.cursor()
    c = cur.execute(
        "select count(distinct(node_id)) from announce where hash = ? and timestamp > strftime('%s','now','-1 day')",
        (blobhash,)
    ).fetchone()[0]
    cur.close()
    return c


async def get_sd_hash(wallet_client, url):
    try:
        resolved_txos = Outputs.from_base64(await wallet_client.send_request('blockchain.claimtrie.resolve', [url]))
        if not resolved_txos.txos:
            return None
        raw_txs = await wallet_client.send_request('blockchain.transaction.get_batch', [txid for (txid, height) in resolved_txos.txs])
        txo_proto = resolved_txos.txos[0]
        txid = txo_proto.tx_hash[::-1].hex()
        raw_tx_hex, _ = raw_txs[txid]
        txo = Transaction(bytes.fromhex(raw_tx_hex)).outputs[txo_proto.nout]
        return txo.claim.stream.source.sd_hash
    except Exception as err:  # claim is not a stream, stream has no source, protobuf err, etc
        if isinstance(err, asyncio.CancelledError):
            raise err
        log.exception("failed to get sd_hash")
        return None


async def api_handler(request):
    return web.Response(text="tracker OK")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ShutdownErr:
        pass
