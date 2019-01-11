import argparse
import asyncio
import aiohttp
import time

from aiohttp import ClientConnectorError
from lbrynet import conf
from lbrynet.schema.uri import parse_lbry_uri
from lbrynet.extras.daemon.DaemonConsole import LBRYAPIClient


def extract_uris(response):
    uris = list()
    for key in response:
        for value in response[key]:
            uris.append(value)

    return uris


async def get_frontpage_uris():
    session = aiohttp.ClientSession()
    try:
        response = await session.get("https://api.lbry.io/file/list_homepage", timeout=10.0)
        if response.status != 200:
            print("API returned non 200 code!!")
            return
        body = await response.json()
        await session.close()
        uris = extract_uris(body['data']['Uris'])
        return uris
    finally:
        await session.close()


async def main():
    uris = await get_frontpage_uris()
    print("got %i uris" % len(uris))
    api = await LBRYAPIClient.get_client()

    try:
        await api.status()
    except (ClientConnectorError, ConnectionError):
        await api.session.close()
        print("Could not connect to daemon. Are you sure it's running?")
        return

    first_byte_times = []

    for uri in uris:
        await api.call(
            "file_delete", {
                "delete_from_download_dir": True,
                "delete_all": True,
                "claim_name": parse_lbry_uri(uri).name
            }
        )

    for i, uri in enumerate(uris):
        start = time.time()
        try:
            await api.call("get", {"uri": uri})
            first_byte = time.time()
            first_byte_times.append(first_byte - start)
            print(f"{i + 1}/{len(uris)} - {first_byte - start} {uri}")
        except:
            print(f"{i + 1}/{len(uris)} -  timed out in {time.time() - start} {uri}")
        await api.call(
            "file_delete", {
                "delete_from_download_dir": True,
                "claim_name": parse_lbry_uri(uri).name
            }
        )

    avg = sum(first_byte_times) / len(first_byte_times)
    print()
    print(f"Average time to first byte: {avg} ({len(first_byte_times)} streams)")
    print(f"Started {len(first_byte_times)} Timed out {len(uris) - len(first_byte_times)}")

    await api.session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", default=None)
    parser.add_argument("--wallet_dir", default=None)
    parser.add_argument("--download_directory", default=None)
    args = parser.parse_args()
    conf.initialize_settings(
        data_dir=args.data_dir, wallet_dir=args.wallet_dir, download_dir=args.download_directory
    )
    asyncio.run(main())
