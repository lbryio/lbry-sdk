import logging

from lbrynet.metadata.Validator import Validator, skip_validate
from lbrynet.conf import CURRENCIES

log = logging.getLogger(__name__)


def verify_supported_currency(fee):
    assert len(fee) == 1
    for c in fee:
        assert c in CURRENCIES
    return True


def verify_amount(x):
    return isinstance(x, float) or isinstance(x, int) and x > 0


class LBCFeeValidator(Validator):
    FV001 = "0.0.1"
    CURRENT_FEE_VERSION = FV001

    FEE_REVISIONS = {}

    FEE_REVISIONS[FV001] = [
        (Validator.REQUIRE, 'amount', verify_amount),
        (Validator.REQUIRE, 'address', skip_validate),
    ]

    FEE_MIGRATIONS = []

    current_version = CURRENT_FEE_VERSION
    versions = FEE_REVISIONS
    migrations = FEE_MIGRATIONS

    def __init__(self, fee):
        Validator.__init__(self, fee)


class BTCFeeValidator(Validator):
    FV001 = "0.0.1"
    CURRENT_FEE_VERSION = FV001

    FEE_REVISIONS = {}

    FEE_REVISIONS[FV001] = [
        (Validator.REQUIRE, 'amount',verify_amount),
        (Validator.REQUIRE, 'address', skip_validate),
    ]

    FEE_MIGRATIONS = []

    current_version = CURRENT_FEE_VERSION
    versions = FEE_REVISIONS
    migrations = FEE_MIGRATIONS

    def __init__(self, fee):
        Validator.__init__(self, fee)


class USDFeeValidator(Validator):
    FV001 = "0.0.1"
    CURRENT_FEE_VERSION = FV001

    FEE_REVISIONS = {}

    FEE_REVISIONS[FV001] = [
        (Validator.REQUIRE, 'amount',verify_amount),
        (Validator.REQUIRE, 'address', skip_validate),
    ]

    FEE_MIGRATIONS = []

    current_version = CURRENT_FEE_VERSION
    versions = FEE_REVISIONS
    migrations = FEE_MIGRATIONS

    def __init__(self, fee):
        Validator.__init__(self, fee)


class LBRYFeeValidator(Validator):
    CV001 = "0.0.1"
    CURRENT_CURRENCY_VERSION = CV001

    CURRENCY_REVISIONS = {}

    CURRENCY_REVISIONS[CV001] = [
        (Validator.OPTIONAL, 'BTC', BTCFeeValidator.validate),
        (Validator.OPTIONAL, 'USD', USDFeeValidator.validate),
        (Validator.OPTIONAL, 'LBC', LBCFeeValidator.validate),
    ]

    CURRENCY_MIGRATIONS = []

    current_version = CURRENT_CURRENCY_VERSION
    versions = CURRENCY_REVISIONS
    migrations = CURRENCY_MIGRATIONS

    def __init__(self, fee_dict):
        Validator.__init__(self, fee_dict)
        self.currency_symbol = self.keys()[0]
        self.amount = self._get_amount()
        self.address = self[self.currency_symbol]['address']

    def _get_amount(self):
        amt = self[self.currency_symbol]['amount']
        if isinstance(amt, float):
            return amt
        else:
            try:
                return float(amt)
            except TypeError:
                log.error('Failed to convert %s to float', amt)
                raise
