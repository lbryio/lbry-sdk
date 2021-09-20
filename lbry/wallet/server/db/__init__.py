import enum


class DB_PREFIXES(enum.Enum):
    claim_to_support = b'K'
    support_to_claim = b'L'

    claim_to_txo = b'E'
    txo_to_claim = b'G'

    claim_to_channel = b'I'
    channel_to_claim = b'J'

    claim_short_id_prefix = b'F'
    claim_effective_amount_prefix = b'D'

    undo_claimtrie = b'M'

    HISTORY_PREFIX = b'A'
    TX_PREFIX = b'B'
    BLOCK_HASH_PREFIX = b'C'
    HEADER_PREFIX = b'H'
    TX_NUM_PREFIX = b'N'
    TX_COUNT_PREFIX = b'T'
    UNDO_PREFIX = b'U'
    TX_HASH_PREFIX = b'X'

    HASHX_UTXO_PREFIX = b'h'
    HIST_STATE = b'state-hist'
    UTXO_STATE = b'state-utxo'
    UTXO_PREFIX = b'u'
    HASHX_HISTORY_PREFIX = b'x'
