import asyncio
from aiohttp import web

from lbry.blob_exchange.serialization import BlobRequest, BlobResponse
from lbry.dht.constants import generate_id
from lbry.dht.node import Node
from lbry.dht.peer import make_kademlia_peer, PeerManager
from lbry.extras.daemon.storage import SQLiteStorage

loop = asyncio.get_event_loop()
NODE = Node(
    loop, PeerManager(loop), generate_id(), 60600, 60600, 3333, None,
    storage=SQLiteStorage(None, ":memory:", loop, loop.time)
)


async def check_p2p(ip, port):
    writer = None
    try:
        reader, writer = await asyncio.open_connection(ip, port)
        writer.write(BlobRequest.make_request_for_blob_hash('0'*96).serialize())
        return BlobResponse.deserialize(await reader.readuntil(b'}')).get_address_response().lbrycrd_address
    except OSError:
        return None
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()


async def check_dht(ip, port):
    peer = make_kademlia_peer(None, ip, udp_port=int(port))
    return await NODE.protocol.get_rpc_peer(peer).ping()


async def endpoint_p2p(request):
    p2p_port = request.match_info.get('p2p_port', "3333")
    try:
        address = await asyncio.wait_for(check_p2p(request.remote, p2p_port), 3)
    except asyncio.TimeoutError:
        address = None
    return {"status": address is not None, "port": p2p_port, "payment_address": address}


async def endpoint_dht(request):
    dht_port = request.match_info.get('dht_port', "3333")
    try:
        response = await check_dht(request.remote, dht_port)
    except asyncio.TimeoutError:
        response = None
    return {"status": response == b'pong', "port": dht_port}


async def endpoint_default(request):
    return {"dht_status": await endpoint_dht(request), "p2p_status": await endpoint_p2p(request)}


def as_json_response_wrapper(endpoint):
    async def json_endpoint(*args, **kwargs):
        return web.json_response(await endpoint(*args, **kwargs))
    return json_endpoint


app = web.Application()
app.add_routes([web.get('/', as_json_response_wrapper(endpoint_default)),
                web.get('/dht/{dht_port}', as_json_response_wrapper(endpoint_dht)),
                web.get('/p2p/{p2p_port}', as_json_response_wrapper(endpoint_p2p))])

if __name__ == '__main__':
    loop.create_task(NODE.start_listening("0.0.0.0"))
    web.run_app(app, port=60666)