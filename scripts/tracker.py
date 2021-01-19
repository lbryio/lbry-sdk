import asyncio
import logging
import signal
import time
from aioupnp import upnp
import sqlite3
import pickle
from os import path
from pprint import pprint


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

    peer_manager = peer.PeerManager(loop)
    u = await upnp.UPnP.discover()

    db = sqlite3.connect(data_dir + "/tracker.sqlite3")
    db.execute(
        'CREATE TABLE IF NOT EXISTS log (local_id TEXT, hash TEXT, node_id TEXT, ip TEXT, port INT, timestamp INT)'
    )
    # curr = db.cursor()
    # res = curr.execute("SELECT 1, 2, 3")
    # for items in res:
    #     print(items)

    num_nodes = 16
    start_port = 4444
    known_node_urls = [("lbrynet1.lbry.com", 4444), ("lbrynet2.lbry.com", 4444), ("lbrynet3.lbry.com", 4444)]
    external_ip = await u.get_external_ip()

    nodes = []

    try:
        for i in range(num_nodes):
            assert i < 16 # my ghetto int -> node_id converter requires this
            node_id = '0123456789abcdef'[i] + '0' * 95
            # pprint(node_id)
            port = start_port + i
            await u.get_next_mapping(port, "UDP", "lbry dht tracker", port)
            n = node.Node(loop, peer_manager, node_id=bytes.fromhex(node_id), external_ip=external_ip,
                          udp_port=port, internal_udp_port=port, peer_port=3333)

            persisted_peers =[]
            if path.exists(state_dir + node_id):
                with open(state_dir + node_id, 'rb') as f:
                    state = pickle.load(f)
                    # pprint(state.routing_table_peers)
                    # pprint(state.datastore)
                    print(f'{node_id[:8]}: loaded {len(state.routing_table_peers)} rt peers, {len(state.datastore)} in store')
                    n.load_state(state)
                    persisted_peers = state.routing_table_peers

            n.start("0.0.0.0", known_node_urls, persisted_peers)
            nodes.append(n)

        await asyncio.gather(*map(lambda n: n.started_listening.wait(), nodes), loop=loop)
        print("joined")

        queue = asyncio.Queue(maxsize=100*num_nodes)
        for n in nodes:
            asyncio.create_task(drain(n, queue))

        while True:
            (n, node_id, ip, method, args) = await queue.get()
            local_node_id = bytes.hex(n.protocol.node_id)
            if method != b'store':
                # print(f"{local_node_id[:8]}: {method} from {bytes.hex(node_id)} ({ip})")
                continue

            blob_hash, token, port, original_publisher_id, age = args[:5]
            print(f"STORE to {local_node_id[:8]} from {bytes.hex(node_id)[:8]} ({ip}) for blob {bytes.hex(blob_hash)[:8]}")

            try:
                cur = db.cursor()
                cur.execute('INSERT INTO log (local_id, hash, node_id, ip, port, timestamp) VALUES (?,?,?,?,?,?)',
                            (local_node_id, bytes.hex(blob_hash), bytes.hex(node_id), ip, port, int(time.time())))
                db.commit()
                cur.close()
            except sqlite3.Error as err:
                print("failed insert", err)
    finally:
        print("shutting down")
        for n in nodes:
            node_id = bytes.hex(n.protocol.node_id)
            n.stop()
            state = n.get_state()
            with open(state_dir + node_id, 'wb') as f:
                # pprint(state.routing_table_peers)
                # pprint(state.datastore)
                print(f'{node_id[:8]}: saved {len(state.routing_table_peers)} rt peers, {len(state.datastore)} in store')
                pickle.dump(state, f)
        db.close()
        await u.delete_port_mapping(n.protocol.udp_port, "UDP")


class ShutdownErr(BaseException):
    pass


def shutdown():
    print("got interrupt signal...")
    raise ShutdownErr()


async def drain(n, q):
    print(f'drain started on {bytes.hex(n.protocol.node_id)[:8]}')
    while True:
        (node_id, ip, method, args) = await n.protocol.event_queue.get()
        try:
            q.put_nowait((n, node_id, ip, method, args))
        except asyncio.QueueFull:
            pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ShutdownErr:
        pass
