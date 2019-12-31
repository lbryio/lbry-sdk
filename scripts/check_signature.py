import argparse
import sqlite3
from binascii import hexlify
from lbry.wallet.transaction import Output


def check(db_path, claim_id):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    claim = db.execute('select * from claim where claim_id=?', (claim_id,)).fetchone()
    if not claim:
        print('Could not find claim.')
        return
    channel = db.execute('select * from claim where claim_hash=?', (claim['channel_hash'],)).fetchone()
    if not channel:
        print('Could not find channel for this claim.')
    print(f"Claim: {claim['claim_name']}")
    print(f"Channel: {channel['claim_name']}")
    print(f"Signature: {hexlify(claim['signature']).decode()}")
    print(f"Digest: {hexlify(claim['signature_digest']).decode()}")
    print(f"Pubkey: {hexlify(channel['public_key_bytes']).decode()}")
    print("Valid: {}".format(Output.is_signature_valid(
        claim['signature'], claim['signature_digest'], channel['public_key_bytes']
    )))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('db_path')
    parser.add_argument('claim_id')
    args = parser.parse_args()
    check(args.db_path, args.claim_id)
