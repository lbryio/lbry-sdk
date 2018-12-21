import binascii
import asyncio
import typing
from lbrynet.peer import Peer
from lbrynet.blob.blob_file import BlobFile
from lbrynet.blob_exchange.client import BlobExchangeClientProtocol
from lbrynet.dht.node import Node


async def download_single_blob(node: Node, blob: BlobFile, peer_timeout: typing.Optional[int] = 3,
                               peer_connect_timeout: typing.Optional[int] = 1):
    blob_protocols: typing.Dict[Peer, asyncio.Future] = {}

    finished = asyncio.Future(loop=loop)

    def cancel_others(peer: Peer):
        def _cancel_others(f: asyncio.Future):
            result = f.result()
            if len(result):
                while blob_protocols:
                    other_peer, f = blob_protocols.popitem()
                    if other_peer is not peer and not f.done() and not f.cancelled():
                        f.cancel()
                finished.set_result(peer)
        return _cancel_others

    async def download_blob():
        async for peers in node.get_iterative_value_finder(binascii.unhexlify(blob.blob_hash.encode()),
                                                           bottom_out_limit=5):
            for peer in peers:
                if peer not in blob_protocols:
                    task = asyncio.ensure_future(asyncio.create_task())
                    task.add_done_callback(cancel_others(peer))
                    blob_protocols[peer] = task

    download_task = asyncio.create_task(download_blob())

    def cancel_download_task(_):
        if not download_task.cancelled() and not download_task.done():
            download_task.cancel()

    finished.add_done_callback(cancel_download_task)

    return await finished
