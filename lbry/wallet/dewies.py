import textwrap
from .util import coins_to_satoshis, satoshis_to_coins


def lbc_to_dewies(lbc: str) -> int:
    try:
        return coins_to_satoshis(lbc)
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
    return satoshis_to_coins(dewies)


def dict_values_to_lbc(d):
    lbc_dict = {}
    for key, value in d.items():
        if isinstance(value, int):
            lbc_dict[key] = dewies_to_lbc(value)
        elif isinstance(value, dict):
            lbc_dict[key] = dict_values_to_lbc(value)
        else:
            lbc_dict[key] = value
    return lbc_dict
