from torba.basescript import BaseInputScript, BaseOutputScript, Template
from torba.basescript import PUSH_SINGLE, OP_DROP, OP_2DROP


class InputScript(BaseInputScript):
    pass


class OutputScript(BaseOutputScript):

    # lbry custom opcodes
    OP_CLAIM_NAME = 0xb5
    OP_SUPPORT_CLAIM = 0xb6
    OP_UPDATE_CLAIM = 0xb7
    OP_PURCHASE_CLAIM = 0xb8

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

    PURCHASE_CLAIM_OPCODES = (
        OP_PURCHASE_CLAIM, PUSH_SINGLE('claim_id'), OP_2DROP
    )
    PURCHASE_CLAIM_PUBKEY = Template('purchase_claim+pay_pubkey_hash', (
            PURCHASE_CLAIM_OPCODES + BaseOutputScript.PAY_PUBKEY_HASH.opcodes
    ))
    PURCHASE_CLAIM_SCRIPT = Template('purchase_claim+pay_script_hash', (
            PURCHASE_CLAIM_OPCODES + BaseOutputScript.PAY_SCRIPT_HASH.opcodes
    ))

    templates = BaseOutputScript.templates + [
        CLAIM_NAME_PUBKEY,
        CLAIM_NAME_SCRIPT,
        SUPPORT_CLAIM_PUBKEY,
        SUPPORT_CLAIM_SCRIPT,
        UPDATE_CLAIM_PUBKEY,
        UPDATE_CLAIM_SCRIPT,
        PURCHASE_CLAIM_PUBKEY,
        PURCHASE_CLAIM_SCRIPT
    ]

    @classmethod
    def pay_claim_name_pubkey_hash(cls, claim_name, claim, pubkey_hash):
        return cls(template=cls.CLAIM_NAME_PUBKEY, values={
            'claim_name': claim_name,
            'claim': claim,
            'pubkey_hash': pubkey_hash
        })

    @classmethod
    def purchase_claim_pubkey_hash(cls, claim_id, pubkey_hash):
        return cls(template=cls.PURCHASE_CLAIM_PUBKEY, values={
            'claim_id': claim_id,
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
    def is_purchase_claim(self):
        return self.template.name.startswith('purchase_claim+')

    @property
    def is_claim_involved(self):
        return any((
            self.is_claim_name, self.is_support_claim,
            self.is_update_claim, self.is_purchase_claim
        ))
