import enum


@enum.unique
class DB_PREFIXES(enum.Enum):
    claim_to_support = b'K'
    support_to_claim = b'L'

    claim_to_txo = b'E'
    txo_to_claim = b'G'

    claim_to_channel = b'I'
    channel_to_claim = b'J'

    claim_short_id_prefix = b'F'
    effective_amount = b'D'
    claim_expiration = b'O'

    claim_takeover = b'P'
    pending_activation = b'Q'
    activated_claim_and_support = b'R'
    active_amount = b'S'

    repost = b'V'
    reposted_claim = b'W'

    undo = b'M'
    claim_diff = b'Y'

    tx = b'B'
    block_hash = b'C'
    header = b'H'
    tx_num = b'N'
    tx_count = b'T'
    tx_hash = b'X'
    utxo = b'u'
    hashx_utxo = b'h'
    hashx_history = b'x'
    db_state = b's'
