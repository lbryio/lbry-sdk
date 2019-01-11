import argparse
import asyncio
import aiohttp
import keyring
import time

from aiohttp import ClientConnectorError
from lbrynet import conf
from lbrynet.extras.daemon.auth.client import UnAuthAPIClient


def kill_loop():
    loop = asyncio.get_event_loop()
    loop.stop()
    # loop.close()


def extract_uris(response):
    uris = list()
    for key in response:
        for value in response[key]:
            uris.append(value)

    return uris


async def get_frontpage_uris():
    kr = keyring.get_keyring()
    c = kr.get_preferred_collection()
    lbry_keyring = None
    for col in c.get_all_items():
        if col.get_label() == "LBRY/auth_token":
            lbry_keyring = col
            break

    if lbry_keyring is None:
        print("An auth token is needed to fetch the front page uris")
        print("To generate the auth token, run the LBRY app at least once")
        print("Then run the script again")

    lbry_keyring = lbry_keyring.get_secret().decode("ascii")

    session = aiohttp.ClientSession()
    response = await session.get("https://api.lbry.io/file/list_homepage?auth_token={}".format(lbry_keyring))
    if response.status != 200:
        print("API returned non 200 code!!")
        await session.close()
        kill_loop()

    body = await response.json()
    await session.close()
    uris = extract_uris(body['data']['Uris'])
    return uris


async def main():
    uris = await get_frontpage_uris()
    api = await UnAuthAPIClient.from_url(conf.settings.get_api_connection_string())

    try:
        await api.status()
    except (ClientConnectorError, ConnectionError):
        await api.session.close()
        kill_loop()
        print("Could not connect to daemon. Are you sure it's running?")
        return 1

    results = dict()

    # uris = ["what", "holi", "aweqwfq"]
    _sum = 0
    downloaded = len(uris)

    for uri in uris:
        start = time.time()
        resp = await api.call("get", {"uri": uri})
        end = time.time()

        await api.call("file_delete", {"delete_from_download_dir": True,
                                       "delete_all": True,
                                       "claim_name": uri
                                       })

        time_taken = end - start
        results[uri] = time_taken
        _sum += time_taken

        if resp.get('error'):
            results[uri] = "Could not download"
            downloaded -= 1
            _sum -= time_taken

        print(results[uri], uri)

    avg = _sum / downloaded
    print()
    print("Average time taken:", avg)
    print("Downloaded {} Not Downloaded {}".format(downloaded, len(uris) - downloaded))

    await api.session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir")
    parser.add_argument("--wallet_dir")
    parser.add_argument("--download_directory")
    args = parser.parse_args()

    conf.initialize_settings(data_dir=args.data_dir, wallet_dir=args.wallet_dir, download_dir=args.download_directory)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
