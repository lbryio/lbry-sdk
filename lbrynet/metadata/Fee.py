import logging
import fee_schemas

from lbrynet.metadata.StructuredDict import StructuredDict

log = logging.getLogger(__name__)


class FeeValidator(StructuredDict):
    def __init__(self, fee):
        self._versions = [
            ('0.0.1', fee_schemas.VER_001, None)
        ]

        StructuredDict.__init__(self, fee, fee.get('ver', '0.0.1'))

        self.currency_symbol = self.keys()[0]
        self.amount = self._get_amount()
        self.address = self[self.currency_symbol]['address']

    def _get_amount(self):
        amt = self[self.currency_symbol]['amount']
        try:
            return float(amt)
        except TypeError:
            log.error('Failed to convert fee amount %s to float', amt)
            raise


class LBCFeeValidator(StructuredDict):
    pass


class BTCFeeValidator(StructuredDict):
    pass


class USDFeeValidator(StructuredDict):
    pass
