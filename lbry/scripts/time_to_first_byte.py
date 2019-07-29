import os
import sys
import json
import argparse
import asyncio
import time

import aiohttp
from aiohttp import ClientConnectorError
from lbry import __version__
from lbry.blob.blob_file import MAX_BLOB_SIZE
from lbry.conf import Config
from lbry.extras.daemon.client import daemon_rpc
from lbry.extras import system_info


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


async def wait_for_done(conf, claim_name, timeout):
    blobs_completed, last_completed = 0, time.time()
    while True:
        file = (await daemon_rpc(conf, "file_list", claim_name=claim_name))[0]
        if file['status'] in ['finished', 'stopped']:
            return True, file['blobs_completed'], file['blobs_in_stream']
        elif blobs_completed < int(file['blobs_completed']):
            blobs_completed, last_completed = int(file['blobs_completed']), time.time()
        elif (time.time() - last_completed) > timeout:
            return False, file['blobs_completed'], file['blobs_in_stream']
        await asyncio.sleep(1.0)


async def main(cmd_args=None):
    print('Time to first byte started using parameters:')
    for key, value in vars(cmd_args).items():
        print(f"{key}: {value}")
    conf = Config()
    url_to_claim = {}
    try:
        for page in range(1, cmd_args.download_pages + 1):
            start = time.perf_counter()
            kwargs = {
                'page': page,
                # 'claim_type': 'stream',
                'order_by': ['trending_global'],
                'no_totals': True
            }

            # if not cmd_args.allow_fees:
            #     kwargs['fee_amount'] = 0

            response = await daemon_rpc(
                conf, 'claim_search', **kwargs
            )
            if 'error' in response or not response.get('items'):
                print(f'Error getting claim list page {page}:')
                print(response)
                return 1
            else:
                url_to_claim.update({
                    claim['permanent_url']: claim for claim in response['items']
                })
            print(f'Claim search page {page} took: {time.time() - start}')
    except (ClientConnectorError, ConnectionError):
        print("Could not connect to daemon")
        return 1
    print("**********************************************")

    print(f"Attempting to download {len(url_to_claim)} claim_search streams")

    first_byte_times = []
    download_speeds = []
    download_successes = []
    failed_to = {}

    await asyncio.gather(*(
        daemon_rpc(conf, 'file_delete', delete_from_download_dir=True, claim_name=claim['name'])
        for claim in url_to_claim.values() if not cmd_args.keep_files
    ))

    for i, (url, claim) in enumerate(url_to_claim.items()):
        start = time.time()
        response = await daemon_rpc(conf, 'get', uri=url, save_file=not cmd_args.head_blob_only)
        if 'error' in response:
            print(f"{i + 1}/{len(url_to_claim)} - failed to start {url}: {response['error']}")
            failed_to[url] = 'start'
            if cmd_args.exit_on_error:
                return
            continue
        first_byte = time.time()
        first_byte_times.append(first_byte - start)
        print(f"{i + 1}/{len(url_to_claim)} - {first_byte - start} {url}")
        if not cmd_args.head_blob_only:
            downloaded, amount_downloaded, blobs_in_stream = await wait_for_done(
                conf, claim['name'], cmd_args.stall_download_timeout
            )
            if downloaded:
                download_successes.append(url)
            else:
                failed_to[url] = 'finish'
            mbs = round((blobs_in_stream * (MAX_BLOB_SIZE - 1)) / (time.time() - start) / 1000000, 2)
            download_speeds.append(mbs)
            print(f"downloaded {amount_downloaded}/{blobs_in_stream} blobs for {url} at "
                  f"{mbs}mb/s")
        if not cmd_args.keep_files:
            await daemon_rpc(conf, 'file_delete', delete_from_download_dir=True, claim_name=claim['name'])
        await asyncio.sleep(0.1)

    print("**********************************************")
    result = f"Started {len(first_byte_times)} of {len(url_to_claim)} attempted front page streams\n"
    if first_byte_times:
        result += f"Worst first byte time: {round(max(first_byte_times), 2)}\n" \
                  f"Best first byte time: {round(min(first_byte_times), 2)}\n" \
                  f"95% confidence time-to-first-byte: {confidence(first_byte_times, 1.984)}s\n" \
                  f"99% confidence time-to-first-byte:  {confidence(first_byte_times, 2.626)}s\n" \
                  f"Variance: {variance(first_byte_times)}\n"
    if download_successes:
        result += f"Downloaded {len(download_successes)}/{len(url_to_claim)}\n" \
                  f"Best stream download speed: {round(max(download_speeds), 2)}mb/s\n" \
                  f"Worst stream download speed: {round(min(download_speeds), 2)}mb/s\n" \
                  f"95% confidence download speed: {confidence(download_speeds, 1.984, False)}mb/s\n" \
                  f"99% confidence download speed:  {confidence(download_speeds, 2.626, False)}mb/s\n"

    for reason in ('start', 'finish'):
        failures = [url for url, why in failed_to.items() if reason == why]
        if failures:
            result += f"\nFailed to {reason}:\n" + "\n".join(failures)
    print(result)

    webhook = os.environ.get('TTFB_SLACK_TOKEN', None)
    if webhook:
        await report_to_slack(result, webhook)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow_fees", action='store_true')
    parser.add_argument("--exit_on_error", action='store_true')
    parser.add_argument("--stall_download_timeout", default=0, type=int)
    parser.add_argument("--keep_files", action='store_true')
    parser.add_argument("--head_blob_only", action='store_true')
    parser.add_argument("--download_pages", type=int, default=10)
    sys.exit(asyncio.run(main(cmd_args=parser.parse_args())) or 0)
