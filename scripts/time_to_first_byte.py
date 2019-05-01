import os
import json
import argparse
import asyncio
import aiohttp
import time

from aiohttp import ClientConnectorError
from lbrynet import __version__
from lbrynet.blob.blob_file import MAX_BLOB_SIZE
from lbrynet.conf import Config
from lbrynet.schema.uri import parse_lbry_uri
from lbrynet.extras.daemon.client import daemon_rpc
from lbrynet.extras import system_info


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


def confidence(times, z, plus_err=True):
    mean = sum(times) / len(times)
    standard_dev = (sum(((t - sum(times) / len(times)) ** 2.0 for t in times)) / len(times)) ** 0.5
    err = (z * standard_dev) / (len(times) ** 0.5)
    return f"{round((mean + err) if plus_err else (mean - err), 3)}"


def variance(times):
    mean = sum(times) / len(times)
    return round(sum(((i - mean) ** 2.0 for i in times)) / (len(times) - 1), 3)


async def wait_for_done(conf, uri, timeout):
    name = uri.split("#")[0]
    last_complete = 0
    hang_count = 0
    while True:
        files = await daemon_rpc(conf, "file_list", claim_name=name)
        file = files[0]
        if file['status'] in ['finished', 'stopped']:
            return True, file['blobs_completed'], file['blobs_in_stream']
        if last_complete < int(file['blobs_completed']):
            hang_count = 0
            last_complete = int(file['blobs_completed'])
        else:
            hang_count += 1
            await asyncio.sleep(1.0)
        if hang_count > timeout:
            return False, file['blobs_completed'], file['blobs_in_stream']


async def main(uris=None, cmd_args=None):
    if not uris:
        uris = await get_frontpage_uris()
    conf = Config()
    try:
        await daemon_rpc(conf, 'status')
    except (ClientConnectorError, ConnectionError):
        print("Could not connect to daemon")
        return 1
    print(f"Checking {len(uris)} uris from the front page")
    print("**********************************************")

    resolvable = []
    async def __resolve(name):
        resolved = await daemon_rpc(conf, 'resolve', urls=[name])
        if 'error' not in resolved.get(name, {}):
            if ("fee" not in resolved[name]['claim']['value']) or cmd_args.allow_fees:
                resolvable.append(name)
            else:
                print(f"{name} has a fee, skipping it")
        else:
            print(f"failed to resolve {name}: {resolved[name]['error']}")
    await asyncio.gather(*(__resolve(name) for name in uris))
    print(f"attempting to download {len(resolvable)}/{len(uris)} frontpage streams")

    first_byte_times = []
    download_speeds = []
    download_successes = []
    failed_to_start = []
    download_failures = []

    for uri in resolvable:
        await daemon_rpc(conf, 'file_delete', delete_from_download_dir=True, claim_name=parse_lbry_uri(uri).name)

    for i, uri in enumerate(resolvable):
        start = time.time()
        try:
            await daemon_rpc(conf, 'get', uri=uri, save_file=True)
            first_byte = time.time()
            first_byte_times.append(first_byte - start)
            print(f"{i + 1}/{len(resolvable)} - {first_byte - start} {uri}")
            downloaded, amount_downloaded, blobs_in_stream = await wait_for_done(
                conf, uri, cmd_args.stall_download_timeout
            )
            if downloaded:
                download_successes.append(uri)
            else:
                download_failures.append(uri)
            mbs = round((blobs_in_stream * (MAX_BLOB_SIZE - 1)) / (time.time() - start) / 1000000, 2)
            download_speeds.append(mbs)
            print(f"downloaded {amount_downloaded}/{blobs_in_stream} blobs for {uri} at "
                  f"{mbs}mb/s")
        except Exception as e:
            print(f"{i + 1}/{len(uris)} - failed to start {uri}: {e}")
            failed_to_start.append(uri)
            if cmd_args.exit_on_error:
                return
        if cmd_args.delete_after_download:
            await daemon_rpc(conf, 'file_delete', delete_from_download_dir=True, claim_name=parse_lbry_uri(uri).name)
        await asyncio.sleep(0.1)

    print("**********************************************")
    result = f"Started {len(first_byte_times)} of {len(resolvable)} attempted front page streams\n" \
             f"Worst first byte time: {round(max(first_byte_times), 2)}\n" \
             f"Best first byte time: {round(min(first_byte_times), 2)}\n" \
             f"95% confidence time-to-first-byte: {confidence(first_byte_times, 1.984)}s\n" \
             f"99% confidence time-to-first-byte:  {confidence(first_byte_times, 2.626)}s\n" \
             f"Variance: {variance(first_byte_times)}\n" \
             f"Downloaded {len(download_successes)}/{len(resolvable)}\n" \
             f"Best stream download speed: {round(max(download_speeds), 2)}mb/s\n" \
             f"Worst stream download speed: {round(min(download_speeds), 2)}mb/s\n" \
             f"95% confidence download speed: {confidence(download_speeds, 1.984, False)}mb/s\n" \
             f"99% confidence download speed:  {confidence(download_speeds, 2.626, False)}mb/s\n"

    if failed_to_start:
        result += "\nFailed to start:" + "\n".join([f for f in failed_to_start])
    if download_failures:
        result += "\nFailed to finish:" + "\n".join([f for f in download_failures])
    print(result)

    webhook = os.environ.get('TTFB_SLACK_TOKEN', None)
    if webhook:
        await report_to_slack(result, webhook)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    #parser.add_argument("--data_dir")
    #parser.add_argument("--wallet_dir")
    #parser.add_argument("--download_directory")
    parser.add_argument("--allow_fees", action='store_true')
    parser.add_argument("--exit_on_error", action='store_true')
    parser.add_argument("--stall_download_timeout", default=10, type=int)
    parser.add_argument("--delete_after_download", action='store_true')
    asyncio.run(main(cmd_args=parser.parse_args()))
