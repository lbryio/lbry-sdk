from torba.basescript import BaseInputScript, BaseOutputScript, Template
from torba.basescript import PUSH_SINGLE, PUSH_INTEGER, OP_DROP, OP_2DROP, PUSH_SUBSCRIPT, OP_VERIFY


class InputScript(BaseInputScript):
    pass


class OutputScript(BaseOutputScript):

    # lbry custom opcodes

    # checks
    OP_PRICECHECK = 0xb0  # checks that the BUY output is >= SELL price

    # tx types
    OP_CLAIM_NAME = 0xb5
    OP_SUPPORT_CLAIM = 0xb6
    OP_UPDATE_CLAIM = 0xb7
    OP_SELL_CLAIM = 0xb8
    OP_BUY_CLAIM = 0xb9

    CLAIM_NAME_OPCODES = (
        OP_CLAIM_NAME, PUSH_SINGLE('claim_name'), PUSH_SINGLE('claim'),
        OP_2DROP, OP_DROP
    )
    CLAIM_NAME_PUBKEY = Template('claim_name+pay_pubkey_hash', (
        CLAIM_NAME_OPCODES + BaseOutputScript.PAY_PUBKEY_HASH.opcodes
    ))
    CLAIM_NAME_SCRIPT = Template('claim_name+pay_script_hash', (
        CLAIM_NAME_OPCODES + BaseOutputScript.PAY_SCRIPT_HASH.opcodes
    ))

    SUPPORT_CLAIM_OPCODES = (
        OP_SUPPORT_CLAIM, PUSH_SINGLE('claim_name'), PUSH_SINGLE('claim_id'),
        OP_2DROP, OP_DROP
    )
    SUPPORT_CLAIM_PUBKEY = Template('support_claim+pay_pubkey_hash', (
        SUPPORT_CLAIM_OPCODES + BaseOutputScript.PAY_PUBKEY_HASH.opcodes
    ))
    SUPPORT_CLAIM_SCRIPT = Template('support_claim+pay_script_hash', (
        SUPPORT_CLAIM_OPCODES + BaseOutputScript.PAY_SCRIPT_HASH.opcodes
    ))

    UPDATE_CLAIM_OPCODES = (
        OP_UPDATE_CLAIM, PUSH_SINGLE('claim_name'), PUSH_SINGLE('claim_id'), PUSH_SINGLE('claim'),
        OP_2DROP, OP_2DROP
    )
    UPDATE_CLAIM_PUBKEY = Template('update_claim+pay_pubkey_hash', (
        UPDATE_CLAIM_OPCODES + BaseOutputScript.PAY_PUBKEY_HASH.opcodes
    ))
    UPDATE_CLAIM_SCRIPT = Template('update_claim+pay_script_hash', (
        UPDATE_CLAIM_OPCODES + BaseOutputScript.PAY_SCRIPT_HASH.opcodes
    ))

    SELL_SCRIPT = Template('sell_script', (
        OP_VERIFY, OP_DROP, OP_DROP, OP_DROP, PUSH_INTEGER('price'), OP_PRICECHECK
    ))
    SELL_CLAIM = Template('sell_claim+pay_script_hash', (
        OP_SELL_CLAIM, PUSH_SINGLE('claim_id'), PUSH_SUBSCRIPT('sell_script', SELL_SCRIPT),
        PUSH_SUBSCRIPT('receive_script', BaseInputScript.REDEEM_SCRIPT), OP_2DROP, OP_2DROP
    ) + BaseOutputScript.PAY_SCRIPT_HASH.opcodes)

    BUY_CLAIM = Template('buy_claim+pay_script_hash', (
        OP_BUY_CLAIM, PUSH_SINGLE('sell_id'),
        PUSH_SINGLE('claim_id'), PUSH_SINGLE('claim_version'),
        PUSH_SINGLE('owner_pubkey_hash'), PUSH_SINGLE('negotiation_signature'),
        OP_2DROP, OP_2DROP, OP_2DROP,
    ) + BaseOutputScript.PAY_SCRIPT_HASH.opcodes)

    templates = BaseOutputScript.templates + [
        CLAIM_NAME_PUBKEY,
        CLAIM_NAME_SCRIPT,
        SUPPORT_CLAIM_PUBKEY,
        SUPPORT_CLAIM_SCRIPT,
        UPDATE_CLAIM_PUBKEY,
        UPDATE_CLAIM_SCRIPT,
        SELL_CLAIM, SELL_SCRIPT,
        BUY_CLAIM,
    ]

    @classmethod
    def pay_claim_name_pubkey_hash(cls, claim_name, claim, pubkey_hash):
        return cls(template=cls.CLAIM_NAME_PUBKEY, values={
            'claim_name': claim_name,
            'claim': claim,
            'pubkey_hash': pubkey_hash
        })

    @classmethod
    def pay_update_claim_pubkey_hash(cls, claim_name, claim_id, claim, pubkey_hash):
        return cls(template=cls.UPDATE_CLAIM_PUBKEY, values={
            'claim_name': claim_name,
            'claim_id': claim_id,
            'claim': claim,
            'pubkey_hash': pubkey_hash
        })

    @classmethod
    def pay_support_pubkey_hash(cls, claim_name: bytes, claim_id: bytes, pubkey_hash: bytes):
        return cls(template=cls.SUPPORT_CLAIM_PUBKEY, values={
            'claim_name': claim_name,
            'claim_id': claim_id,
            'pubkey_hash': pubkey_hash
        })

    @classmethod
    def sell_script(cls, price):
        return cls(template=cls.SELL_SCRIPT, values={
            'price': price,
        })

    @classmethod
    def sell_claim(cls, claim_id, price, signatures, pubkeys):
        return cls(template=cls.SELL_CLAIM, values={
            'claim_id': claim_id,
            'sell_script': OutputScript.sell_script(price),
            'receive_script': InputScript.redeem_script(signatures, pubkeys)
        })

    @classmethod
    def buy_claim(cls, sell_id, claim_id, claim_version, owner_pubkey_hash, negotiation_signature):
        return cls(template=cls.BUY_CLAIM, values={
            'sell_id': sell_id,
            'claim_id': claim_id,
            'claim_version': claim_version,
            'owner_pubkey_hash': owner_pubkey_hash,
            'negotiation_signature': negotiation_signature,
        })

    @property
    def is_claim_name(self):
        return self.template.name.startswith('claim_name+')

    @property
    def is_update_claim(self):
        return self.template.name.startswith('update_claim+')

    @property
    def is_support_claim(self):
        return self.template.name.startswith('support_claim+')

    @property
    def is_sell_claim(self):
        return self.template.name.startswith('sell_claim+')

    @property
    def is_buy_claim(self):
        return self.template.name.startswith('buy_claim+')

    @property
    def is_claim_involved(self):
        return any((
            self.is_claim_name, self.is_support_claim, self.is_update_claim,
            self.is_sell_claim, self.is_buy_claim
        ))
