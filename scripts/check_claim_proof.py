#!/usr/bin/env python3

import sys
import json
import subprocess
from binascii import hexlify, unhexlify
from os.path import basename
from lbry.crypto.hash import double_sha256
from lbry.wallet.claim_proofs import get_hash_for_outpoint


def lbrycrd(cli_path: str, *args: str, decode: bool = True) -> str:
    rsp = subprocess.check_output((cli_path,) + args)
    return json.loads(rsp) if decode else rsp.strip()


def script(cli_path: str, name: str) -> None:
    height = lbrycrd(cli_path, "getblockchaininfo")["blocks"]
    block_hash = lbrycrd(cli_path, "getblockhash", str(height), decode=False)
    claimtrie_root_hash = lbrycrd(cli_path, "getblock", block_hash)["nameclaimroot"]

    claim = lbrycrd(cli_path, "getclaimbybid", name, "0", block_hash)
    proof = lbrycrd(cli_path, 'getclaimproofbybid', name, "0", block_hash)

    if not claim:
        print(f"No claims for {name}")
        return

    print(f"Checking name proof for {name} at block {height} (block hash {block_hash.decode('ascii')})")
    print(f"Claimtrie root hash is {claimtrie_root_hash}")

    proof_hash = get_hash_for_outpoint(unhexlify(claim["txId"])[::-1], claim["n"], claim["lastTakeoverHeight"])
    for p in proof["pairs"]:
        if p["odd"]:  # odd = 1 = the missing hash is coming from the right side of the binary merkle trie
            proof_hash = double_sha256(unhexlify(p["hash"])[::-1] + proof_hash)
        else:  # even = 0 = left side
            proof_hash = double_sha256(proof_hash + unhexlify(p["hash"])[::-1])

    proof_hex = hexlify(proof_hash[::-1]).decode('ascii')
    print(f"Proof hash is          {proof_hex}")

    if proof_hex == claimtrie_root_hash:
        print("Proof is valid")
    else:
        print("INVALID PROOF")


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {basename(sys.argv[0])} LBRYCRD_CLI_PATH NAME")
        print("")
        print(f"Example: {basename(sys.argv[0])} /usr/local/bin/lbrycrd-cli @lbry")
        sys.exit(1)
    script(sys.argv[1], sys.argv[2])
