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

    ensureCliIsOnPathAndServerIsRunning()

    wallet = getWallet(args.wallet)
    addresses = wallet.addresses(True)
    for addr in addresses[:-1]:
        printBalance(wallet, addr)
        saveAddr(wallet, addr)
    # on the last one, rescan.  Don't rescan early for sake of efficiency
    addr = addresses[-1]
    printBalance(wallet, addr)
    saveAddr(wallet, addr, "true")


def ensureCliIsOnPathAndServerIsRunning():
    try:
        output = subprocess.check_output(['lbrycrd-cli', 'getinfo'])
    except OSError:
        print 'Failed to run: lbrycrd-cli needs to be on the PATH'
        sys.exit(1)
    except subprocess.CalledProcessError:
        print 'Failed to run: could not connect to the lbrycrd server.'
        print 'Make sure it is running and able to be connected to.'
        print 'One way to do this is to run:'
        print '      lbrycrdd -server -printtoconsole'
        sys.exit(1)


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
        print "Failed to run: No wallet to migrate"
        sys.exit(1)
    return Wallet(storage)


def saveAddr(wallet, addr, rescan="false"):
    keys = wallet.get_private_key(addr, None)
    assert len(keys) == 1, 'Address {} has {} keys.  Expected 1'.format(addr, len(keys))
    key = keys[0]
    # copied from lbrycrd.regenerate_key
    b = lbrycrd.ASecretToSecret(key)
    pkey = b[0:32]
    is_compressed = lbrycrd.is_compressed(key)
    wif = pkeyToWif(pkey, is_compressed)
    subprocess.check_call(
        ['lbrycrd-cli', 'importprivkey', wif, "", rescan])
    validateAddress(addr)


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
