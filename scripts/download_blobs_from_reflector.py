"""A test script that downloads blobs from a reflector server"""
import argparse
import itertools
import json
import random
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('reflector_ip')
    parser.add_argument('--ssh-key')
    parser.add_argument('--size', type=int, default=100)
    parser.add_argument('--batch', type=int, default=10)
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('--hashes', help='file listing hashes in json')
    args = parser.parse_args()

    if args.hashes:
        hashes = readHashes(args.hashes)
    else:
        hashes = getHashes(args.reflector_ip, args.ssh_key)
    if len(hashes) > args.size:
        selected_hashes = random.sample(hashes, args.size)
    else:
        print 'Only {} hashes are available'.format(hashes)
        selected_hashes = hashes

    successes = 0
    for hashes in grouper(selected_hashes, args.batch):
        hashes = filter(None, hashes)
        successes += downloadHashes(args.reflector_ip, hashes, args.timeout)
    print 'Downloaded {} / {}'.format(successes, len(selected_hashes))


def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx
    args = [iter(iterable)] * n
    return itertools.izip_longest(fillvalue=fillvalue, *args)


def readHashes(hash_file):
    with open(hash_file) as f:
        return json.load(f)


def getHashes(ip, key=None):
    key = ['-i', key] if key else []
    hashes = subprocess.check_output(['ssh'] + key +
        ['lbry@{}'.format(ip), '/opt/venvs/lbrynet/bin/lbrynet-cli', 'get_blob_hashes'])
    return json.loads(hashes)


def downloadHashes(ip, blob_hashes, timeout=30):
    processes = [
        subprocess.Popen(
            [
                'python',
                'download_blob_from_peer.py',
                '--timeout', str(timeout), '{}:3333'.format(ip), blob_hash,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for blob_hash in blob_hashes
    ]
    for p, h in zip(processes, blob_hashes):
        stdout, stderr = p.communicate()
        print p.returncode, h
        if p.returncode != 0:
            print 'Failed to download', h
            print stdout
            print stderr
    return sum(1 for p in processes if p.returncode == 0)


if __name__ == '__main__':
    sys.exit(main())
