# pylint: skip-file

from sqlalchemy import (
    MetaData, Table, Column, ForeignKey,
    LargeBinary, Text, SmallInteger, Integer, BigInteger, Boolean
)


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
    Column('block_filter', LargeBinary, nullable=True)
)


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


TXO = Table(
    'txo', metadata,
    Column('tx_hash', LargeBinary, ForeignKey(TX.columns.tx_hash)),
    Column('txo_hash', LargeBinary, primary_key=True),
    Column('address', Text),
    Column('position', SmallInteger),
    Column('amount', BigInteger),
    Column('script_offset', Integer),
    Column('script_length', Integer),
    Column('is_spent', Boolean, server_default='0'),
    Column('is_reserved', Boolean, server_default='0'),
    Column('txo_type', SmallInteger, server_default='0'),
    Column('claim_id', Text, nullable=True),
    Column('claim_hash', LargeBinary, nullable=True),
    Column('claim_name', Text, nullable=True),
)

txo_join_account = TXO.join(AccountAddress, TXO.columns.address == AccountAddress.columns.address)


TXI = Table(
    'txi', metadata,
    Column('tx_hash', LargeBinary, ForeignKey(TX.columns.tx_hash)),
    Column('txo_hash', LargeBinary, ForeignKey(TXO.columns.txo_hash), primary_key=True),
    Column('address', Text, nullable=True),
    Column('position', SmallInteger),
)

txi_join_account = TXI.join(AccountAddress, TXI.columns.address == AccountAddress.columns.address)


Claim = Table(
    'claim', metadata,
    Column('claim_hash', LargeBinary, primary_key=True),
    Column('claim_id', Text),
    Column('claim_name', Text),
    Column('normalized', Text),
    Column('address', Text),
    Column('txo_hash', LargeBinary, ForeignKey(TXO.columns.txo_hash)),
    Column('tx_position', SmallInteger),
    Column('amount', BigInteger),
    Column('timestamp', Integer),  # last updated timestamp
    Column('creation_timestamp', Integer),
    Column('height', Integer),  # last updated height
    Column('creation_height', Integer),
    Column('activation_height', Integer, nullable=True),
    Column('expiration_height', Integer, nullable=True),
    Column('takeover_height', Integer, nullable=True),
    Column('is_controlling', Boolean, server_default='0'),
    Column('release_time', Integer, nullable=True),

    # normalized#shortest-unique-claim_id
    Column('short_url', Text, nullable=True),
    # channel's-short_url/normalized#shortest-unique-claim_id-within-channel
    Column('canonical_url', Text, nullable=True),

    Column('title', Text, nullable=True),
    Column('author', Text, nullable=True),
    Column('description', Text, nullable=True),

    Column('claim_type', SmallInteger),
    Column('claim_reposted_count', Integer, server_default='0'),
    Column('supports_in_claim_count', Integer, server_default='0'),

    # streams
    Column('stream_type', Text, nullable=True),
    Column('media_type', Text, nullable=True),
    Column('fee_amount', BigInteger, server_default='0'),
    Column('fee_currency', Text, nullable=True),
    Column('duration', Integer, nullable=True),

    # reposts
    Column('reposted_claim_hash', LargeBinary, nullable=True),

    # claims which are channels
    Column('public_key', LargeBinary, nullable=True),
    Column('public_key_hash', LargeBinary, nullable=True),
    Column('public_key_height', Integer, server_default='0'),  # height at which public key was last changed
    Column('claims_in_channel_count', Integer, server_default='0'),

    # claims which are inside channels
    Column('channel_hash', LargeBinary, nullable=True),
    Column('signature', LargeBinary, nullable=True),
    Column('signature_digest', LargeBinary, nullable=True),
    Column('is_signature_valid', Boolean, server_default='0'),

    Column('support_amount', BigInteger, server_default='0'),
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


Support = Table(
    'support', metadata,

    Column('txo_hash', LargeBinary, ForeignKey(TXO.columns.txo_hash), primary_key=True),
    Column('claim_hash', LargeBinary, ForeignKey(TXO.columns.claim_hash)),
    Column('address', Text),
    Column('tx_position', SmallInteger),
    Column('activation_height', Integer, nullable=True),
    Column('expiration_height', Integer, nullable=True),
    Column('amount', BigInteger),
    Column('height', Integer),

    # support metadata
    Column('emoji', Text),

    # signed supports
    Column('channel_hash', LargeBinary, nullable=True),
    Column('signature', LargeBinary, nullable=True),
    Column('signature_digest', LargeBinary, nullable=True),
    Column('is_signature_valid', Boolean, server_default='0'),
)


Takeover = Table(
    'takeover', metadata,
    Column('normalized', Text),
    Column('claim_hash', LargeBinary, ForeignKey(TXO.columns.claim_hash)),
    Column('height', Integer),
)
