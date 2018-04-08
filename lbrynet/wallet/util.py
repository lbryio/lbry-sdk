import logging
import os
import re
from decimal import Decimal
import json
from .constants import NO_SIGNATURE

log = logging.getLogger(__name__)


def subclass_tuple(name, base):
    return type(name, (base,), {'__slots__': ()})


def normalize_version(v):
    return [int(x) for x in re.sub(r'(\.0+)*$', '', v).split(".")]


def json_decode(x):
    try:
        return json.loads(x, parse_float=Decimal)
    except:
        return x


def user_dir():
    if "HOME" in os.environ:
        return os.path.join(os.environ["HOME"], ".lbryum")
    elif "APPDATA" in os.environ:
        return os.path.join(os.environ["APPDATA"], "LBRYum")
    elif "LOCALAPPDATA" in os.environ:
        return os.path.join(os.environ["LOCALAPPDATA"], "LBRYum")
    elif 'ANDROID_DATA' in os.environ:
        try:
            import jnius
            env = jnius.autoclass('android.os.Environment')
            _dir = env.getExternalStorageDirectory().getPath()
            return _dir + '/lbryum/'
        except ImportError:
            pass
        return "/sdcard/lbryum/"
    else:
        # raise Exception("No home directory found in environment variables.")
        return


def format_satoshis(x, is_diff=False, num_zeros=0, decimal_point=8, whitespaces=False):
    from locale import localeconv
    if x is None:
        return 'unknown'
    x = int(x)  # Some callers pass Decimal
    scale_factor = pow(10, decimal_point)
    integer_part = "{:n}".format(int(abs(x) / scale_factor))
    if x < 0:
        integer_part = '-' + integer_part
    elif is_diff:
        integer_part = '+' + integer_part
    dp = localeconv()['decimal_point']
    fract_part = ("{:0" + str(decimal_point) + "}").format(abs(x) % scale_factor)
    fract_part = fract_part.rstrip('0')
    if len(fract_part) < num_zeros:
        fract_part += "0" * (num_zeros - len(fract_part))
    result = integer_part + dp + fract_part
    if whitespaces:
        result += " " * (decimal_point - len(fract_part))
        result = " " * (15 - len(result)) + result
    return result.decode('utf8')


def rev_hex(s):
    return s.decode('hex')[::-1].encode('hex')


def int_to_hex(i, length=1):
    s = hex(i)[2:].rstrip('L')
    s = "0" * (2 * length - len(s)) + s
    return rev_hex(s)


def hex_to_int(s):
    return int('0x' + s[::-1].encode('hex'), 16)


def var_int(i):
    # https://en.bitcoin.it/wiki/Protocol_specification#Variable_length_integer
    if i < 0xfd:
        return int_to_hex(i)
    elif i <= 0xffff:
        return "fd" + int_to_hex(i, 2)
    elif i <= 0xffffffff:
        return "fe" + int_to_hex(i, 4)
    else:
        return "ff" + int_to_hex(i, 8)


# This function comes from bitcointools, bct-LICENSE.txt.
def long_hex(bytes):
    return bytes.encode('hex_codec')


# This function comes from bitcointools, bct-LICENSE.txt.
def short_hex(bytes):
    t = bytes.encode('hex_codec')
    if len(t) < 11:
        return t
    return t[0:4] + "..." + t[-4:]


def parse_sig(x_sig):
    s = []
    for sig in x_sig:
        if sig[-2:] == '01':
            s.append(sig[:-2])
        else:
            assert sig == NO_SIGNATURE
            s.append(None)
    return s


def is_extended_pubkey(x_pubkey):
    return x_pubkey[0:2] in ['fe', 'ff']
