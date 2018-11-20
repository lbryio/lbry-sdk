import textwrap
from torba.client.util import coins_to_satoshis, satoshis_to_coins


def lbc_to_dewies(lbc):
    try:
        return coins_to_satoshis(lbc)
    except ValueError:
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
    return satoshis_to_coins(dewies)
