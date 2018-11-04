import re
import textwrap
from torba.client.constants import COIN


def lbc_to_dewies(lbc):
    if isinstance(lbc, str):
        result = re.search(r'^(\d{1,10})\.(\d{1,8})$', lbc)
        if result is not None:
            whole, fractional = result.groups()
            return int(whole+fractional.ljust(8, "0"))
    raise ValueError(textwrap.dedent(
        """
        Decimal inputs require a value in the ones place and in the tenths place
        separated by a period. The value provided, '{}', is not of the correct
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
        """.format(lbc)
    ))


def dewies_to_lbc(dewies):
    lbc = '{:.8f}'.format(dewies / COIN).rstrip('0')
    if lbc.endswith('.'):
        return lbc+'0'
    else:
        return lbc
