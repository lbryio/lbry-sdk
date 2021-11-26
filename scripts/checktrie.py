import sys
import asyncio
from binascii import hexlify

from lbry.wallet.server.db.writer import SQLDB
from lbry.wallet.server.coin import LBC
from lbry.wallet.server.daemon import Daemon


def hex_reverted(value: bytes) -> str:
    return hexlify(value[::-1]).decode()


def match(name, what, value, expected):
    if value != expected:
        print(f'{name}: {what} mismatch, {value} is not {expected}')
    return value == expected


def checkrecord(record, expected_winner, expected_claim):
    assert record['is_controlling'] == record['claim_hash'], dict(record)
    name = record['normalized']
    claim_id = hex_reverted(record['claim_hash'])
    takover = record['activation_height']
    if not expected_winner:
        print(f"{name} not on lbrycrd. We have {claim_id} at {takover} takeover height.")
        return
    if not match(name, 'claim id', claim_id, expected_winner['claimId']):
        print(f"-- {name} has the wrong winner")
    if not expected_claim:
        print(f'{name}: {claim_id} not found, we possibly have an abandoned claim as winner')
        return
    match(name, 'height', record['height'], expected_claim['height'])
    match(name, 'activation height', takover, expected_claim['valid at height'])
    match(name, 'name', record['normalized'], expected_claim['normalized_name'])
    match(name, 'amount', record['amount'], expected_claim['amount'])
    match(name, 'effective amount', record['effective_amount'], expected_claim['effective amount'])
    match(name, 'txid', hex_reverted(record['txo_hash'][:-4]), expected_claim['txid'])
    match(name, 'nout', int.from_bytes(record['txo_hash'][-4:], 'little', signed=False), expected_claim['n'])


async def checkcontrolling(daemon: Daemon, db: SQLDB):
    records, names, futs = [], [], []
    for record in db.get_claims('claimtrie.claim_hash as is_controlling, claim.*', is_controlling=True):
        records.append(record)
        claim_id = hex_reverted(record['claim_hash'])
        names.append((record['normalized'], (claim_id,), "", True))  # last parameter is IncludeValues
        if len(names) > 50000:
            futs.append(daemon._send_vector('getclaimsfornamebyid', names))
            names.clear()
    if names:
        futs.append(daemon._send_vector('getclaimsfornamebyid', names))
        names.clear()

    while futs:
        winners, claims = futs.pop(0), futs.pop(0)
        for winner, claim in zip(await winners, await claims):
            checkrecord(records.pop(0), winner, claim)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("usage: <db_file_path> <lbrycrd_url>")
        sys.exit(1)
    db_path, lbrycrd_url = sys.argv[1:]  # pylint: disable=W0632
    daemon = Daemon(LBC(), url=lbrycrd_url)
    db = SQLDB(None, db_path)
    db.open()

    asyncio.get_event_loop().run_until_complete(checkcontrolling(daemon, db))
