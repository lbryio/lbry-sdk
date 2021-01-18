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
    state_file = data_dir + '/nodestate'
    loop = asyncio.get_event_loop()

    try:
        loop.add_signal_handler(signal.SIGINT, shutdown)
        loop.add_signal_handler(signal.SIGTERM, shutdown)
    except NotImplementedError:
        pass  # Not implemented on Windows

    peer_manager = peer.PeerManager(loop)
    u = await upnp.UPnP.discover()
    await u.get_next_mapping(4444, "UDP", "lbry dht tracker", 4444)
    my_node_id = "38b060a751ac96384cd9327eb1b1e36a21fdb71114be07434c0cc7bf63f6e1da274edebfe76f65fbd51ad2f14898b95b"
    n = node.Node(loop, peer_manager, node_id=bytes.fromhex(my_node_id), external_ip=(await u.get_external_ip()),
                  udp_port=4444, internal_udp_port=4444, peer_port=4444)

    db = sqlite3.connect(data_dir + "/tracker.sqlite3")
    db.execute(
        '''CREATE TABLE IF NOT EXISTS log (hash TEXT, node_id TEXT, ip TEXT, port INT, timestamp INT)'''
    )
    # curr = db.cursor()
    # res = curr.execute("SELECT 1, 2, 3")
    # for items in res:
    #     print(items)

    try:
        known_node_urls=[("lbrynet1.lbry.com", 4444), ("lbrynet2.lbry.com", 4444), ("lbrynet3.lbry.com", 4444)]
        persisted_peers =[]
        if path.exists(state_file):
            with open(state_file, 'rb') as f:
                state = pickle.load(f)
                # pprint(state.routing_table_peers)
                # pprint(state.datastore)
                print(f'loaded {len(state.routing_table_peers)} rt peers, {len(state.datastore)} in store')
                n.load_state(state)
                persisted_peers = state.routing_table_peers

        n.start("0.0.0.0", known_node_urls, persisted_peers)
        await n.started_listening.wait()
        print("joined")
        # jack = peer.make_kademlia_peer(
        #     bytes.fromhex("38b060a751ac96384cd9327eb1b1e36a21fdb71114be07434c0cc7bf63f6e1da274edebfe76f65fbd51ad2f14898b95c"),
        #     "216.19.244.226", udp_port=4444,
        # )
        # print(await n.protocol.get_rpc_peer(jack).ping())

        await dostuff(n, db)
    finally:
        print("shutting down")
        n.stop()
        state = n.get_state()
        with open(state_file, 'wb') as f:
            # pprint(state.routing_table_peers)
            # pprint(state.datastore)
            print(f'saved {len(state.routing_table_peers)} rt peers, {len(state.datastore)} in store')
            pickle.dump(state, f)
        db.close()
        await u.delete_port_mapping(4444, "UDP")


async def dostuff(n, db):
    # gather
    # as_completed
    # wait
    # wait_for

    # make a task to loop over the things in the node. those tasks drain into one combined queue
    # t = asyncio.create_task for each node
    # keep the t
    # handle teardown at the end
    # 

    while True:
        (node_id, ip, method, args) = await n.protocol.event_queue.get()
        if method == b'store':
            blob_hash, token, port, original_publisher_id, age = args[:5]
            print(f"STORE from {bytes.hex(node_id)} ({ip}) for blob {bytes.hex(blob_hash)}")

            try:
                cur = db.cursor()
                cur.execute('INSERT INTO log (hash, node_id, ip, port, timestamp) VALUES (?,?,?,?,?)',
                           (bytes.hex(blob_hash), bytes.hex(node_id), ip, port, int(time.time())))
                db.commit()
                cur.close()
            except sqlite3.Error as err:
                print("failed insert", err)
        else:
            pass
            # print(f"{method} from {bytes.hex(node_id)} ({ip})")


class ShutdownErr(BaseException):
    pass


def shutdown():
    print("got interrupt signal...")
    raise ShutdownErr()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ShutdownErr:
        pass
