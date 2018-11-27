from collections import OrderedDict

from lbrynet.schema.address import encode_address, decode_address
from lbrynet.schema.schema import CURRENCY_NAMES, CURRENCY_MAP
from lbrynet.schema.schema.fee import Fee as FeeHelper
from lbrynet.schema.proto import fee_pb2


def migrate(fee):
    if len(list(fee.keys())) == 3 and 'currency' in fee and 'amount' in fee and 'address' in fee:
        return FeeHelper.load({
            "version": "_0_0_1",
            "currency": fee['currency'],
            "amount": fee['amount'],
            "address": decode_address(fee['address'])
        })
    if len(list(fee.keys())) > 1:
        raise Exception("Invalid fee")

    currency = list(fee.keys())[0]
    amount = fee[currency]['amount']
    address = fee[currency]['address']

    return FeeHelper.load({
        "version": "_0_0_1",
        "currency": currency,
        "amount": amount,
        "address": decode_address(address)
    })


class Fee(OrderedDict):
    def __init__(self, fee):
        if (len(fee) == 4 and "version" in fee and "currency" in fee
           and "amount" in fee and "address" in fee):
            OrderedDict.__init__(self, fee)
        else:
            OrderedDict.__init__(self, Fee.load_protobuf(migrate(fee)))

    @property
    def currency(self):
        return self['currency']

    @property
    def address(self):
        return self['address']

    @property
    def amount(self):
        return self['amount']

    @property
    def version(self):
        return self['version']

    @property
    def protobuf(self):
        pb = {
            "version": self.version,
            "currency": CURRENCY_MAP[self.currency],
            "address": decode_address(self.address),
            "amount": self.amount
        }
        return FeeHelper.load(pb)

    @classmethod
    def load_protobuf(cls, pb):
        return cls({
                "version": pb.version,
                "currency": CURRENCY_NAMES[pb.currency],
                "address": encode_address(pb.address),
                "amount": pb.amount
        })

    @classmethod
    def deserialize(cls, serialized):
        pb = fee_pb2.Fee()
        pb.ParseFromString(serialized)
        return cls.load_protobuf(pb)
