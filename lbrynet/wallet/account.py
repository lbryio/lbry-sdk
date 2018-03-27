import logging

from lbryschema.address import public_key_to_address

from .lbrycrd import deserialize_xkey
from .lbrycrd import CKD_pub

log = logging.getLogger(__name__)


def get_key_chain_from_xpub(xpub):
    _, _, _, chain, key = deserialize_xkey(xpub)
    return key, chain


class AddressSequence:

    def __init__(self, derived_keys, gap, age_checker, pub_key, chain_key):
        self.gap = gap
        self.is_old = age_checker
        self.pub_key = pub_key
        self.chain_key = chain_key
        self.derived_keys = derived_keys
        self.addresses = [
            public_key_to_address(key.decode('hex'))
            for key in derived_keys
        ]

    def generate_next_address(self):
        new_key, _ = CKD_pub(self.pub_key, self.chain_key, len(self.derived_keys))
        address = public_key_to_address(new_key)
        self.derived_keys.append(new_key.encode('hex'))
        self.addresses.append(address)
        return address

    def has_gap(self):
        if len(self.addresses) < self.gap:
            return False
        for address in self.addresses[-self.gap:]:
            if self.is_old(address):
                return False
        return True

    def ensure_enough_addresses(self):
        starting_length = len(self.addresses)
        while not self.has_gap():
            self.generate_next_address()
        return self.addresses[starting_length:]


class Account:

    def __init__(self, data, receiving_gap, change_gap, age_checker):
        self.xpub = data['xpub']
        master_key, master_chain = get_key_chain_from_xpub(data['xpub'])
        self.receiving = AddressSequence(
            data.get('receiving', []), receiving_gap, age_checker,
            *CKD_pub(master_key, master_chain, 0)
        )
        self.change = AddressSequence(
            data.get('change', []), change_gap, age_checker,
            *CKD_pub(master_key, master_chain, 1)
        )
        self.is_old = age_checker

    def as_dict(self):
        return {
            'receiving': self.receiving.derived_keys,
            'change': self.change.derived_keys,
            'xpub': self.xpub
        }

    @property
    def sequences(self):
        return self.receiving, self.change
