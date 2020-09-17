# pylint: skip-file

from sqlalchemy import (
    MetaData, Table, Column, ForeignKey,
    LargeBinary, Text, SmallInteger, Integer, BigInteger, Boolean,
)
from .constants import TXO_TYPES, CLAIM_TYPE_CODES


SCHEMA_VERSION = '1.4'


metadata = MetaData()


Version = Table(
    'version', metadata,
    Column('version', Text, primary_key=True),
)


PubkeyAddress = Table(
    'pubkey_address', metadata,
    Column('address', Text, primary_key=True),
    Column('used_times', Integer, server_default='0'),
)


AccountAddress = Table(
    'account_address', metadata,
    Column('account', Text, primary_key=True),
    Column('address', Text, ForeignKey(PubkeyAddress.columns.address), primary_key=True),
    Column('chain', SmallInteger),
    Column('pubkey', LargeBinary),
    Column('chain_code', LargeBinary),
    Column('n', Integer),
    Column('depth', SmallInteger),
)


Block = Table(
    'block', metadata,
    Column('block_hash', LargeBinary, primary_key=True),
    Column('previous_hash', LargeBinary),
    Column('file_number', SmallInteger),
    Column('height', Integer),
    Column('timestamp', Integer),
)

pg_add_block_constraints_and_indexes = [
    "ALTER TABLE block ADD PRIMARY KEY (block_hash);"
]

BlockFilter = Table(
    'block_filter', metadata,
    Column('block_hash', LargeBinary, primary_key=True),
    Column('block_filter', LargeBinary, nullable=True),
)
join_block_filter = Block.join(BlockFilter, BlockFilter.columns.block_hash == Block.columns.block_hash, full=True)
pg_add_block_filter_constraints_and_indexes = [
    "ALTER TABLE block_filter ADD PRIMARY KEY (block_hash);",
    "ALTER TABLE block_filter ADD CONSTRAINT fk_block_filter "
    " FOREIGN KEY(block_hash) "
	" REFERENCES block(block_hash) "
    " ON DELETE CASCADE;"
]

TX = Table(
    'tx', metadata,
    Column('block_hash', LargeBinary, nullable=True),
    Column('tx_hash', LargeBinary, primary_key=True),
    Column('raw', LargeBinary),
    Column('height', Integer),
    Column('position', SmallInteger),
    Column('timestamp', Integer, nullable=True),
    Column('day', Integer, nullable=True),
    Column('is_verified', Boolean, server_default='FALSE'),
    Column('purchased_claim_hash', LargeBinary, nullable=True),
    Column('tx_filter', LargeBinary, nullable=True)
)


pg_add_tx_constraints_and_indexes = [
    "ALTER TABLE tx ADD PRIMARY KEY (tx_hash);",
]


TXO = Table(
    'txo', metadata,
    Column('tx_hash', LargeBinary, ForeignKey(TX.columns.tx_hash)),
    Column('txo_hash', LargeBinary, primary_key=True),
    Column('address', Text),
    Column('position', SmallInteger),
    Column('amount', BigInteger),
    Column('height', Integer),
    Column('spent_height', Integer, server_default='0'),
    Column('script_offset', Integer),
    Column('script_length', Integer),
    Column('is_reserved', Boolean, server_default='0'),

    # claims
    Column('txo_type', SmallInteger, server_default='0'),
    Column('claim_id', Text, nullable=True),
    Column('claim_hash', LargeBinary, nullable=True),
    Column('claim_name', Text, nullable=True),
    Column('channel_hash', LargeBinary, nullable=True),  # claims in channel
    Column('signature', LargeBinary, nullable=True),
    Column('signature_digest', LargeBinary, nullable=True),

    # channels
    Column('public_key', LargeBinary, nullable=True),
    Column('public_key_hash', LargeBinary, nullable=True),
)

txo_join_account = TXO.join(AccountAddress, TXO.columns.address == AccountAddress.columns.address)


pg_add_txo_constraints_and_indexes = [
    "ALTER TABLE txo ADD PRIMARY KEY (txo_hash);",
    # find appropriate channel public key for signing a content claim
    f"CREATE INDEX txo_channel_hash_by_height_desc_w_pub_key "
    f"ON txo (claim_hash, height desc) INCLUDE (public_key) "
    f"WHERE txo_type={TXO_TYPES['channel']};",
    # for calculating supports on a claim
    f"CREATE INDEX txo_unspent_supports ON txo (claim_hash) INCLUDE (amount) "
    f"WHERE spent_height = 0 AND txo_type={TXO_TYPES['support']};",
    # for finding modified claims in a block range
    f"CREATE INDEX txo_claim_changes "
    f"ON txo (height DESC) INCLUDE (claim_hash, txo_hash) "
    f"WHERE spent_height = 0 AND txo_type IN {tuple(CLAIM_TYPE_CODES)};",
    # for finding claims which need support totals re-calculated in a block range
    f"CREATE INDEX txo_added_supports_by_height ON txo (height DESC) "
    f"INCLUDE (claim_hash) WHERE txo_type={TXO_TYPES['support']};",
    f"CREATE INDEX txo_spent_supports_by_height ON txo (spent_height DESC) "
    f"INCLUDE (claim_hash) WHERE txo_type={TXO_TYPES['support']};",
    "CREATE INDEX txo_tx_height ON txo (height);"
]


TXI = Table(
    'txi', metadata,
    Column('tx_hash', LargeBinary, ForeignKey(TX.columns.tx_hash)),
    Column('txo_hash', LargeBinary, ForeignKey(TXO.columns.txo_hash), primary_key=True),
    Column('address', Text, nullable=True),
    Column('position', SmallInteger),
    Column('height', Integer),
)

txi_join_account = TXI.join(AccountAddress, TXI.columns.address == AccountAddress.columns.address)


pg_add_txi_constraints_and_indexes = [
    "ALTER TABLE txi ADD PRIMARY KEY (txo_hash);",
    "CREATE INDEX txi_tx_height ON txi (height);"
]


Claim = Table(
    'claim', metadata,
    Column('claim_hash', LargeBinary, primary_key=True),
    Column('claim_id', Text),
    Column('claim_name', Text),
    Column('normalized', Text),
    Column('address', Text),
    Column('txo_hash', LargeBinary, ForeignKey(TXO.columns.txo_hash)),
    Column('amount', BigInteger),
    Column('staked_amount', BigInteger),
    Column('timestamp', Integer),  # last updated timestamp
    Column('creation_timestamp', Integer),
    Column('release_time', Integer, nullable=True),
    Column('height', Integer),  # last updated height
    Column('creation_height', Integer),
    Column('activation_height', Integer),
    Column('expiration_height', Integer),
    Column('takeover_height', Integer, nullable=True),
    Column('is_controlling', Boolean),

    # short_url: normalized#shortest-unique-claim_id
    Column('short_url', Text),
    # canonical_url: channel's-short_url/normalized#shortest-unique-claim_id-within-channel
    # canonical_url is computed dynamically

    Column('title', Text, nullable=True),
    Column('author', Text, nullable=True),
    Column('description', Text, nullable=True),

    Column('claim_type', SmallInteger),
    Column('claim_reposted_count', Integer, server_default='0'),
    Column('staked_support_count', Integer, server_default='0'),
    Column('staked_support_amount', BigInteger, server_default='0'),

    # streams
    Column('stream_type', SmallInteger, nullable=True),
    Column('media_type', Text, nullable=True),
    Column('fee_amount', BigInteger, server_default='0'),
    Column('fee_currency', Text, nullable=True),
    Column('duration', Integer, nullable=True),

    # reposts
    Column('reposted_claim_hash', LargeBinary, nullable=True),
    Column('reposted_count', Integer, server_default='0'),

    # claims which are channels
    Column('signed_claim_count', Integer, server_default='0'),
    Column('signed_support_count', Integer, server_default='0'),

    # claims which are inside channels
    Column('channel_hash', LargeBinary, nullable=True),
    Column('is_signature_valid', Boolean, nullable=True),

    Column('trending_group', BigInteger, server_default='0'),
    Column('trending_mixed', BigInteger, server_default='0'),
    Column('trending_local', BigInteger, server_default='0'),
    Column('trending_global', BigInteger, server_default='0'),
)


Tag = Table(
    'tag', metadata,
    Column('claim_hash', LargeBinary),
    Column('tag', Text),
)


pg_add_claim_and_tag_constraints_and_indexes = [
    "ALTER TABLE claim ADD PRIMARY KEY (claim_hash);",
    # for checking if claim is up-to-date
    "CREATE UNIQUE INDEX claim_txo_hash ON claim (txo_hash);",
    # used by takeover process to reset winning claims
    "CREATE INDEX claim_normalized ON claim (normalized);",
    # ordering and search by release_time
    "CREATE INDEX claim_release_time ON claim (release_time DESC NULLs LAST);",
    # used to count()/sum() claims signed by channel
    "CREATE INDEX signed_content ON claim (channel_hash) "
    "INCLUDE (amount) WHERE is_signature_valid;",
    # basic tag indexes
    "ALTER TABLE tag ADD PRIMARY KEY (claim_hash, tag);",
    "CREATE INDEX tags ON tag (tag) INCLUDE (claim_hash);",
]


Support = Table(
    'support', metadata,

    Column('txo_hash', LargeBinary, ForeignKey(TXO.columns.txo_hash), primary_key=True),
    Column('claim_hash', LargeBinary),
    Column('address', Text),
    Column('amount', BigInteger),
    Column('height', Integer),
    Column('timestamp', Integer),

    # support metadata
    Column('emoji', Text),

    # signed supports
    Column('channel_hash', LargeBinary, nullable=True),
    Column('signature', LargeBinary, nullable=True),
    Column('signature_digest', LargeBinary, nullable=True),
    Column('is_signature_valid', Boolean, nullable=True),
)


pg_add_support_constraints_and_indexes = [
    "ALTER TABLE support ADD PRIMARY KEY (txo_hash);",
    # used to count()/sum() supports signed by channel
    "CREATE INDEX signed_support ON support (channel_hash) "
    "INCLUDE (amount) WHERE is_signature_valid;",
]


Stake = Table(
    'stake', metadata,
    Column('claim_hash', LargeBinary),
    Column('height', Integer),
    Column('stake_min', BigInteger),
    Column('stake_max', BigInteger),
    Column('stake_sum', BigInteger),
    Column('stake_count', Integer),
    Column('stake_unique', Integer),
)
