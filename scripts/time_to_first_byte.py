import os
import json
import argparse
import asyncio
import aiohttp
import time

from aiohttp import ClientConnectorError
from lbrynet import __version__
from lbrynet.conf import Config
from lbrynet.schema.uri import parse_lbry_uri
from lbrynet.extras.daemon.client import LBRYAPIClient
from lbrynet.extras import system_info, cli


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


async def report_to_slack(output, webhook):
    payload = {
        "text": f"lbrynet {__version__} ({system_info.get_platform()['platform']}) time to first byte:\n{output}"
    }
    async with aiohttp.request('post', webhook, data=json.dumps(payload)):
        pass


def confidence(times, z):
    mean = sum(times) / len(times)
    standard_dev = (sum(((t - sum(times) / len(times)) ** 2.0 for t in times)) / len(times)) ** 0.5
    err = (z * standard_dev) / (len(times) ** 0.5)
    return f"{round(mean, 3) + round(err, 3)}s"


def variance(times):
    mean = sum(times) / len(times)
    return round(sum(((i - mean) ** 2.0 for i in times)) / (len(times) - 1), 3)


async def wait_for_done(api, uri):
    name = uri.split("#")[0]
    last_complete = 0
    hang_count = 0
    while True:
        files = await api.file_list(claim_name=name)
        file = files[0]
        if file['status'] in ['finished', 'stopped']:
            return True, f"{file['blobs_completed']}/{file['blobs_in_stream']}", int(file['blobs_completed'])
        if last_complete < int(file['blobs_completed']):
            print(f"{file['blobs_completed']}/{file['blobs_in_stream']}...")
            hang_count = 0
            last_complete = int(file['blobs_completed'])
        else:
            hang_count += 1
            await asyncio.sleep(1.0)
        if hang_count > 30:
            return False, f"{file['blobs_completed']}/{file['blobs_in_stream']}", int(file['blobs_completed'])


async def main(start_daemon=True, uris=None):
    if not uris:
        uris = await get_frontpage_uris()
    api = LBRYAPIClient(Config())
    daemon = None
    try:
        await api.status()
    except (ClientConnectorError, ConnectionError):
        print("Could not connect to daemon")
        return 1
    print(f"Checking {len(uris)} uris from the front page")
    print("**********************************************")

    resolvable = []
    for name in uris:
        resolved = await api.resolve(uri=name)
        if 'error' not in resolved.get(name, {}):
            resolvable.append(name)

    print(f"{len(resolvable)}/{len(uris)} are resolvable")

    first_byte_times = []
    downloaded_times = []
    failures = []
    download_failures = []

    for uri in resolvable:
        await api.file_delete(delete_from_download_dir=True, claim_name=parse_lbry_uri(uri).name)

    for i, uri in enumerate(resolvable):
        start = time.time()
        try:
            await api.get(uri)
            first_byte = time.time()
            first_byte_times.append(first_byte - start)
            print(f"{i + 1}/{len(resolvable)} - {first_byte - start} {uri}")
            # downloaded, msg, blobs_in_stream = await wait_for_done(api, uri)
            # if downloaded:
            #     downloaded_times.append((time.time()-start) / downloaded)
            #     print(f"{i + 1}/{len(uris)} - downloaded @ {(time.time()-start) / blobs_in_stream}, {msg} {uri}")
            # else:
            #     print(f"failed to downlload {uri}, got {msg}")
            #     download_failures.append(uri)
        except:
            print(f"{i + 1}/{len(uris)} -  timeout in {time.time() - start} {uri}")
            failures.append(uri)
        await api.file_delete(delete_from_download_dir=True, claim_name=parse_lbry_uri(uri).name)
        await asyncio.sleep(0.1)

    print("**********************************************")
    result = f"Tried to start downloading {len(resolvable)} streams from the front page\n" \
             f"95% confidence time-to-first-byte: {confidence(first_byte_times, 1.984)}\n" \
             f"99% confidence time-to-first-byte:  {confidence(first_byte_times, 2.626)}\n" \
             f"Variance: {variance(first_byte_times)}\n" \
             f"Started {len(first_byte_times)}/{len(resolvable)} streams"
    if failures:
        nt = '\n\t'
        result += f"\nFailures:\n\t{nt.join([f for f in failures])}"
    print(result)
    if daemon:
        await daemon.shutdown()
    # webhook = os.environ.get('TTFB_SLACK_TOKEN', None)
    # if webhook:
    #     await report_to_slack(result, webhook)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir")
    parser.add_argument("--wallet_dir")
    parser.add_argument("--download_directory")
    args = parser.parse_args()
    asyncio.run(main())
