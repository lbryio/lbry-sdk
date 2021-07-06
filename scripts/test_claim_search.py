import asyncio
from lbry.wallet.network import ClientSession
from lbry.wallet.rpc.jsonrpc import RPCError
import logging
import json
import sys

logging.getLogger('lbry.wallet').setLevel(logging.CRITICAL)


async def main():
    try:
        hostname = sys.argv[1]
    except IndexError:
        hostname = 'spv11.lbry.com'

    loop = asyncio.get_event_loop()
    client = ClientSession(network=None, server=(hostname, 50001))
    error = None
    args = {
        'any_tags': ['art'],
        'not_tags': ['xxx', 'porn', 'mature', 'nsfw', 'titan'],
        'order_by': ["name"],
        'offset': 3000,
        'limit': 200,
        'no_totals': False,
    }

    start = loop.time()
    try:
        await client.create_connection()
        try:
            await client.send_request('blockchain.claimtrie.search', args)
        except RPCError as err:
            error = err
        finally:
            await client.close()
    finally:
        print(json.dumps({
            "time": loop.time() - start,
            "error": error.__str__() if error else None,
            "args": args,
        }, indent=4))


if __name__ == "__main__":
    asyncio.run(main())
