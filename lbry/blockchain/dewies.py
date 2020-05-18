import re
import textwrap
from decimal import Decimal

from lbry.constants import COIN


def lbc_to_dewies(lbc: str) -> int:
    try:
        if not isinstance(lbc, str):
            raise ValueError("{coins} must be a string")
        result = re.search(r'^(\d{1,10})\.(\d{1,8})$', lbc)
        if result is not None:
            whole, fractional = result.groups()
            return int(whole + fractional.ljust(8, "0"))
        raise ValueError(f"'{lbc}' is not a valid coin decimal")
    except ValueError:
        raise ValueError(textwrap.dedent(
            f"""
            Decimal inputs require a value in the ones place and in the tenths place
            separated by a period. The value provided, '{lbc}', is not of the correct
            format.

            The following are examples of valid decimal inputs:

            1.0
            0.001
            2.34500
            4534.4
            2323434.0000

            The following are NOT valid:

            83
            .456
            123.
            """
        ))


def dewies_to_lbc(dewies) -> str:
    coins = '{:.8f}'.format(dewies / COIN).rstrip('0')
    if coins.endswith('.'):
        return coins+'0'
    else:
        return coins


def dict_values_to_lbc(d):
    lbc_dict = {}
    for key, value in d.items():
        if isinstance(value, (int, Decimal)):
            lbc_dict[key] = dewies_to_lbc(value)
        elif isinstance(value, dict):
            lbc_dict[key] = dict_values_to_lbc(value)
        else:
            lbc_dict[key] = value
    return lbc_dict
