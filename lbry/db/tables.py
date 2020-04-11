from sqlalchemy import (
    MetaData, Table, Column, ForeignKey,
    Binary, Text, SmallInteger, Integer, Boolean
)


metadata = MetaData()


Version = Table(
    'version', metadata,
    Column('version', Text, primary_key=True),
)


PubkeyAddress = Table(
    'pubkey_address', metadata,
    Column('address', Text, primary_key=True),
    Column('history', Text, nullable=True),
    Column('used_times', Integer, server_default='0'),
)


AccountAddress = Table(
    'account_address', metadata,
    Column('account', Text, primary_key=True),
    Column('address', Text, ForeignKey(PubkeyAddress.columns.address), primary_key=True),
    Column('chain', Integer),
    Column('pubkey', Binary),
    Column('chain_code', Binary),
    Column('n', Integer),
    Column('depth', Integer),
)


Block = Table(
    'block', metadata,
    Column('block_hash', Binary, primary_key=True),
    Column('previous_hash', Binary),
    Column('file_number', SmallInteger),
    Column('height', Integer),
)


TX = Table(
    'tx', metadata,
    Column('block_hash', Binary, nullable=True),
    Column('tx_hash', Binary, primary_key=True),
    Column('raw', Binary),
    Column('height', Integer),
    Column('position', SmallInteger),
    Column('is_verified', Boolean, server_default='FALSE'),
    Column('purchased_claim_hash', Binary, nullable=True),
    Column('day', Integer, nullable=True),
)


TXO = Table(
    'txo', metadata,
    Column('tx_hash', Binary, ForeignKey(TX.columns.tx_hash)),
    Column('txo_hash', Binary, primary_key=True),
    Column('address', Text),
    Column('position', Integer),
    Column('amount', Integer),
    Column('script', Binary),
    Column('is_reserved', Boolean, server_default='0'),
    Column('txo_type', Integer, server_default='0'),
    Column('claim_id', Text, nullable=True),
    Column('claim_hash', Binary, nullable=True),
    Column('claim_name', Text, nullable=True),
    Column('channel_hash', Binary, nullable=True),
    Column('reposted_claim_hash', Binary, nullable=True),
)


TXI = Table(
    'txi', metadata,
    Column('tx_hash', Binary, ForeignKey(TX.columns.tx_hash)),
    Column('txo_hash', Binary, ForeignKey(TXO.columns.txo_hash), primary_key=True),
    Column('address', Text),
    Column('position', Integer),
)
