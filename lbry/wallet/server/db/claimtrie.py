import typing
from typing import Optional
from lbry.wallet.server.db.revertable import RevertablePut, RevertableDelete, RevertableOp, delete_prefix
from lbry.wallet.server.db import DB_PREFIXES
from lbry.wallet.server.db.prefixes import Prefixes

nOriginalClaimExpirationTime = 262974
nExtendedClaimExpirationTime = 2102400
nExtendedClaimExpirationForkHeight = 400155
nNormalizedNameForkHeight = 539940      # targeting 21 March 2019
nMinTakeoverWorkaroundHeight = 496850
nMaxTakeoverWorkaroundHeight = 658300   # targeting 30 Oct 2019
nWitnessForkHeight = 680770             # targeting 11 Dec 2019
nAllClaimsInMerkleForkHeight = 658310   # targeting 30 Oct 2019
proportionalDelayFactor = 32

def get_expiration_height(last_updated_height: int) -> int:
    if last_updated_height < nExtendedClaimExpirationForkHeight:
        return last_updated_height + nOriginalClaimExpirationTime
    return last_updated_height + nExtendedClaimExpirationTime


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


def get_update_effective_amount_ops(name: str, new_effective_amount: int, prev_effective_amount: int, tx_num: int,
                                    position: int, root_tx_num: int, root_position: int, claim_hash: bytes,
                                    signing_hash: Optional[bytes] = None,
                                    claims_in_channel_count: Optional[int] = None):
    assert root_position != root_tx_num, f"{tx_num} {position} {root_tx_num} {root_tx_num}"
    ops = [
        RevertableDelete(
            *Prefixes.claim_effective_amount.pack_item(
                name, prev_effective_amount, tx_num, position, claim_hash, root_tx_num, root_position
            )
        ),
        RevertablePut(
            *Prefixes.claim_effective_amount.pack_item(
                name, new_effective_amount, tx_num, position, claim_hash, root_tx_num, root_position
            )
        )
    ]
    if signing_hash:
        ops.extend([
            RevertableDelete(
                *Prefixes.channel_to_claim.pack_item(
                    signing_hash, name, prev_effective_amount, tx_num, position, claim_hash, claims_in_channel_count
                )
            ),
            RevertablePut(
                *Prefixes.channel_to_claim.pack_item(
                    signing_hash, name, new_effective_amount, tx_num, position, claim_hash, claims_in_channel_count
                )
            )
        ])
    return ops


class StagedClaimtrieItem(typing.NamedTuple):
    name: str
    claim_hash: bytes
    amount: int
    effective_amount: int
    activation_height: int
    expiration_height: int
    tx_num: int
    position: int
    root_claim_tx_num: int
    root_claim_tx_position: int
    signing_hash: Optional[bytes]
    claims_in_channel_count: Optional[int]

    @property
    def is_update(self) -> bool:
        return (self.tx_num, self.position) != (self.root_claim_tx_num, self.root_claim_tx_position)

    def _get_add_remove_claim_utxo_ops(self, add=True):
        """
        get a list of revertable operations to add or spend a claim txo to the key: value database

        :param add: if true use RevertablePut operations, otherwise use RevertableDelete
        :return:
        """
        op = RevertablePut if add else RevertableDelete
        ops = [
            # url resolution by effective amount
            op(
                *Prefixes.claim_effective_amount.pack_item(
                    self.name, self.effective_amount, self.tx_num, self.position, self.claim_hash,
                    self.root_claim_tx_num, self.root_claim_tx_position
                )
            ),
            # claim tip by claim hash
            op(
                *Prefixes.claim_to_txo.pack_item(
                    self.claim_hash, self.tx_num, self.position, self.root_claim_tx_num, self.root_claim_tx_position,
                    self.amount, self.name
                )
            ),
            # short url resolution
            op(
                *Prefixes.claim_short_id.pack_item(
                    self.name, self.claim_hash, self.root_claim_tx_num, self.root_claim_tx_position, self.tx_num,
                    self.position
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
            )
        ]
        if self.signing_hash and self.claims_in_channel_count is not None:
            # claims_in_channel_count can be none if the channel doesnt exist
            ops.extend([
                # channel by stream
                op(
                    *Prefixes.claim_to_channel.pack_item(self.claim_hash, self.signing_hash)
                ),
                # stream by channel
                op(
                    *Prefixes.channel_to_claim.pack_item(
                        self.signing_hash, self.name, self.effective_amount, self.tx_num, self.position,
                        self.claim_hash, self.claims_in_channel_count
                    )
                )
            ])
        return ops

    def get_add_claim_utxo_ops(self) -> typing.List[RevertableOp]:
        return self._get_add_remove_claim_utxo_ops(add=True)

    def get_spend_claim_txo_ops(self) -> typing.List[RevertableOp]:
        return self._get_add_remove_claim_utxo_ops(add=False)

    def get_invalidate_channel_ops(self, db) -> typing.List[RevertableOp]:
        if not self.signing_hash:
            return []
        return [
                   RevertableDelete(*Prefixes.claim_to_channel.pack_item(self.claim_hash, self.signing_hash))
               ] + delete_prefix(db, DB_PREFIXES.channel_to_claim.value + self.signing_hash)

    def get_abandon_ops(self, db) -> typing.List[RevertableOp]:
        packed_name = length_encoded_name(self.name)
        delete_short_id_ops = delete_prefix(
            db, DB_PREFIXES.claim_short_id_prefix.value + packed_name + self.claim_hash
        )
        delete_claim_ops = delete_prefix(db, DB_PREFIXES.claim_to_txo.value + self.claim_hash)
        delete_supports_ops = delete_prefix(db, DB_PREFIXES.claim_to_support.value + self.claim_hash)
        invalidate_channel_ops = self.get_invalidate_channel_ops(db)
        return delete_short_id_ops + delete_claim_ops + delete_supports_ops + invalidate_channel_ops

