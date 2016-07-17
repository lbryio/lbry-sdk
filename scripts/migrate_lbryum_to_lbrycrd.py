import argparse
import hashlib
import json
import subprocess
import sys

import base58

from lbryum import SimpleConfig, Network
from lbryum.wallet import WalletStorage, Wallet
from lbryum.commands import known_commands, Commands
from lbryum import lbrycrd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wallet', help='path to lbryum wallet')
    args = parser.parse_args()

    wallet = getWallet(args.wallet)
    addresses = wallet.addresses(True)
    for addr in addresses[:-1]:
        printBalance(wallet, addr)
        saveAddr(wallet, addr)
        validateAddress(addr)
    # on the last one, rescan.  Don't rescan early for sake of efficiency
    addr = addresses[-1]
    printBalance(wallet, addr)
    saveAddr(wallet, addr, "true")
    validateAddress(addr)


def validateAddress(addr):
    raw_output = subprocess.check_output(
        ['lbrycrd-cli', 'validateaddress', addr])
    output = json.loads(raw_output)
    if not output['isvalid']:
        raise Exception('Address {} is not valid'.format(addr))
    if not output['ismine']:
        raise Exception('Address {} is not yours'.format(addr))


def printBalance(wallet, addr):
    balance = getBalance(wallet, addr)
    print 'Importing private key for %s with balance %s' % (addr, balance)


def getBalance(wallet, addr):
    return sum(wallet.get_addr_balance(addr))


def getWallet(path=None):
    if not path:
        config = SimpleConfig()
        path = config.get_wallet_path()
    storage = WalletStorage(path)
    if not storage.file_exists:
        print "No wallet to migrate"
        return
    return Wallet(storage)


def saveAddr(wallet, addr, rescan="false"):
    keys = wallet.get_private_key(addr, None)
    for key in keys:
        # copied from lbrycrd.regenerate_key
        b = lbrycrd.ASecretToSecret(key)
        pkey = b[0:32]
        is_compressed = lbrycrd.is_compressed(key)
        wif = pkeyToWif(pkey, is_compressed)
        output = subprocess.check_output(
            ['lbrycrd-cli', 'importprivkey', wif, "lbryum import", rescan])
        if output:
            print output


def pkeyToWif(pkey, compressed):
    # Follow https://en.bitcoin.it/wiki/Wallet_import_format
    # to convert from a private key to the wallet import format
    prefix = '\x1c'
    wif = prefix + pkey
    if compressed:
        wif += '\x01'
    intermediate_checksum = hashlib.sha256(wif).digest()
    checksum = hashlib.sha256(intermediate_checksum).digest()
    wif = wif + checksum[:4]
    return base58.b58encode(wif)


def wifToPkey(wif):
    pkey = base58.b58decode(wif)
    return pkey[1:-4]


if __name__ == '__main__':
    sys.exit(main())
