import typing
from typing import Optional
from lbry.wallet.server.db.revertable import RevertablePut, RevertableDelete, RevertableOp
from lbry.wallet.server.db.prefixes import Prefixes, ClaimTakeoverValue, EffectiveAmountPrefixRow
from lbry.wallet.server.db.prefixes import RepostPrefixRow, RepostedPrefixRow


def length_encoded_name(name: str) -> bytes:
    encoded = name.encode('utf-8')
    return len(encoded).to_bytes(2, byteorder='big') + encoded


class StagedClaimtrieSupport(typing.NamedTuple):
    claim_hash: bytes
    tx_num: int
    position: int
    amount: int

    def _get_add_remove_support_utxo_ops(self, add=True):
        """
        get a list of revertable operations to add or spend a support txo to the key: value database

        :param add: if true use RevertablePut operations, otherwise use RevertableDelete
        :return:
        """
        op = RevertablePut if add else RevertableDelete
        return [
            op(
                *Prefixes.claim_to_support.pack_item(self.claim_hash, self.tx_num, self.position, self.amount)
            ),
            op(
                *Prefixes.support_to_claim.pack_item(self.tx_num, self.position, self.claim_hash)
            )
        ]

    def get_add_support_utxo_ops(self) -> typing.List[RevertableOp]:
        return self._get_add_remove_support_utxo_ops(add=True)

    def get_spend_support_txo_ops(self) -> typing.List[RevertableOp]:
        return self._get_add_remove_support_utxo_ops(add=False)


class StagedActivation(typing.NamedTuple):
    txo_type: int
    claim_hash: bytes
    tx_num: int
    position: int
    activation_height: int
    name: str
    amount: int

    def _get_add_remove_activate_ops(self, add=True):
        op = RevertablePut if add else RevertableDelete
        # print(f"\t{'add' if add else 'remove'} {'claim' if self.txo_type == ACTIVATED_CLAIM_TXO_TYPE else 'support'},"
        #       f" {self.tx_num}, {self.position}, activation={self.activation_height}, {self.name}, "
        #       f"amount={self.amount}")
        return [
            op(
                *Prefixes.activated.pack_item(
                    self.txo_type, self.tx_num, self.position, self.activation_height, self.claim_hash, self.name
                )
            ),
            op(
                *Prefixes.pending_activation.pack_item(
                    self.activation_height, self.txo_type, self.tx_num, self.position,
                    self.claim_hash, self.name
                )
            ),
            op(
                *Prefixes.active_amount.pack_item(
                    self.claim_hash, self.txo_type, self.activation_height, self.tx_num, self.position, self.amount
                )
            )
        ]

    def get_activate_ops(self) -> typing.List[RevertableOp]:
        return self._get_add_remove_activate_ops(add=True)

    def get_remove_activate_ops(self) -> typing.List[RevertableOp]:
        return self._get_add_remove_activate_ops(add=False)


def get_remove_name_ops(name: str, claim_hash: bytes, height: int) -> typing.List[RevertableDelete]:
    return [
        RevertableDelete(
            *Prefixes.claim_takeover.pack_item(
                name, claim_hash, height
            )
        )
    ]


def get_takeover_name_ops(name: str, claim_hash: bytes, takeover_height: int,
                          previous_winning: Optional[ClaimTakeoverValue]):
    if previous_winning:
        return [
            RevertableDelete(
                *Prefixes.claim_takeover.pack_item(
                    name, previous_winning.claim_hash, previous_winning.height
                )
            ),
            RevertablePut(
                *Prefixes.claim_takeover.pack_item(
                    name, claim_hash, takeover_height
                )
            )
        ]
    return [
        RevertablePut(
            *Prefixes.claim_takeover.pack_item(
                name, claim_hash, takeover_height
            )
        )
    ]


def get_remove_effective_amount_ops(name: str, effective_amount: int, tx_num: int, position: int, claim_hash: bytes):
    return [
        RevertableDelete(*EffectiveAmountPrefixRow.pack_item(name, effective_amount, tx_num, position, claim_hash))
    ]


def get_add_effective_amount_ops(name: str, effective_amount: int, tx_num: int, position: int, claim_hash: bytes):
    return [
        RevertablePut(*EffectiveAmountPrefixRow.pack_item(name, effective_amount, tx_num, position, claim_hash))
    ]


class StagedClaimtrieItem(typing.NamedTuple):
    name: str
    claim_hash: bytes
    amount: int
    expiration_height: int
    tx_num: int
    position: int
    root_tx_num: int
    root_position: int
    channel_signature_is_valid: bool
    signing_hash: Optional[bytes]
    reposted_claim_hash: Optional[bytes]

    @property
    def is_update(self) -> bool:
        return (self.tx_num, self.position) != (self.root_tx_num, self.root_position)

    def _get_add_remove_claim_utxo_ops(self, add=True):
        """
        get a list of revertable operations to add or spend a claim txo to the key: value database

        :param add: if true use RevertablePut operations, otherwise use RevertableDelete
        :return:
        """
        op = RevertablePut if add else RevertableDelete
        ops = [
            # claim tip by claim hash
            op(
                *Prefixes.claim_to_txo.pack_item(
                    self.claim_hash, self.tx_num, self.position, self.root_tx_num, self.root_position,
                    self.amount, self.channel_signature_is_valid, self.name
                )
            ),
            # claim hash by txo
            op(
                *Prefixes.txo_to_claim.pack_item(self.tx_num, self.position, self.claim_hash, self.name)
            ),
            # claim expiration
            op(
                *Prefixes.claim_expiration.pack_item(
                    self.expiration_height, self.tx_num, self.position, self.claim_hash,
                    self.name
                )
            ),
            # short url resolution
        ]
        ops.extend([
            op(
                *Prefixes.claim_short_id.pack_item(
                    self.name, self.claim_hash.hex()[:prefix_len + 1], self.root_tx_num, self.root_position,
                    self.tx_num, self.position
                )
            ) for prefix_len in range(10)
        ])

        if self.signing_hash and self.channel_signature_is_valid:
            ops.extend([
                # channel by stream
                op(
                    *Prefixes.claim_to_channel.pack_item(
                        self.claim_hash, self.tx_num, self.position, self.signing_hash
                    )
                ),
                # stream by channel
                op(
                    *Prefixes.channel_to_claim.pack_item(
                        self.signing_hash, self.name, self.tx_num, self.position, self.claim_hash
                    )
                )
            ])
        if self.reposted_claim_hash:
            ops.extend([
                op(
                    *Prefixes.repost.pack_item(self.claim_hash, self.reposted_claim_hash)
                ),
                op(
                    *Prefixes.reposted_claim.pack_item(
                        self.reposted_claim_hash, self.tx_num, self.position, self.claim_hash
                    )
                ),

            ])
        return ops

    def get_add_claim_utxo_ops(self) -> typing.List[RevertableOp]:
        return self._get_add_remove_claim_utxo_ops(add=True)

    def get_spend_claim_txo_ops(self) -> typing.List[RevertableOp]:
        return self._get_add_remove_claim_utxo_ops(add=False)

    def get_invalidate_signature_ops(self):
        if not self.signing_hash:
            return []
        ops = [
            RevertableDelete(
                *Prefixes.claim_to_channel.pack_item(
                    self.claim_hash, self.tx_num, self.position, self.signing_hash
                )
            )
        ]
        if self.channel_signature_is_valid:
            ops.extend([
                # delete channel_to_claim/claim_to_channel
                RevertableDelete(
                    *Prefixes.channel_to_claim.pack_item(
                        self.signing_hash, self.name, self.tx_num, self.position, self.claim_hash
                    )
                ),
                # update claim_to_txo with channel_signature_is_valid=False
                RevertableDelete(
                    *Prefixes.claim_to_txo.pack_item(
                        self.claim_hash, self.tx_num, self.position, self.root_tx_num, self.root_position,
                        self.amount, self.channel_signature_is_valid, self.name
                    )
                ),
                RevertablePut(
                    *Prefixes.claim_to_txo.pack_item(
                        self.claim_hash, self.tx_num, self.position, self.root_tx_num, self.root_position,
                        self.amount, False, self.name
                    )
                )
            ])
        return ops

    def invalidate_signature(self) -> 'StagedClaimtrieItem':
        return StagedClaimtrieItem(
            self.name, self.claim_hash, self.amount, self.expiration_height, self.tx_num, self.position,
            self.root_tx_num, self.root_position, False, None, self.reposted_claim_hash
        )
