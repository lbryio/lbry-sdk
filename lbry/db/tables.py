# pylint: skip-file

from sqlalchemy import (
    MetaData, Table, Column, ForeignKey,
    BINARY, TEXT, SMALLINT, INTEGER, BOOLEAN
)


metadata = MetaData()


Version = Table(
    'version', metadata,
    Column('version', TEXT, primary_key=True),
)


PubkeyAddress = Table(
    'pubkey_address', metadata,
    Column('address', TEXT, primary_key=True),
    Column('history', TEXT, nullable=True),
    Column('used_times', INTEGER, server_default='0'),
)


AccountAddress = Table(
    'account_address', metadata,
    Column('account', TEXT, primary_key=True),
    Column('address', TEXT, ForeignKey(PubkeyAddress.columns.address), primary_key=True),
    Column('chain', INTEGER),
    Column('pubkey', BINARY),
    Column('chain_code', BINARY),
    Column('n', INTEGER),
    Column('depth', INTEGER),
)


Block = Table(
    'block', metadata,
    Column('block_hash', BINARY, primary_key=True),
    Column('previous_hash', BINARY),
    Column('file_number', SMALLINT),
    Column('height', INTEGER),
)


TX = Table(
    'tx', metadata,
    Column('block_hash', BINARY, nullable=True),
    Column('tx_hash', BINARY, primary_key=True),
    Column('raw', BINARY),
    Column('height', INTEGER),
    Column('position', SMALLINT),
    Column('is_verified', BOOLEAN, server_default='FALSE'),
    Column('purchased_claim_hash', BINARY, nullable=True),
    Column('day', INTEGER, nullable=True),
)


TXO = Table(
    'txo', metadata,
    Column('tx_hash', BINARY, ForeignKey(TX.columns.tx_hash)),
    Column('txo_hash', BINARY, primary_key=True),
    Column('address', TEXT, ForeignKey(AccountAddress.columns.address)),
    Column('position', INTEGER),
    Column('amount', INTEGER),
    Column('script', BINARY),
    Column('is_reserved', BOOLEAN, server_default='0'),
    Column('txo_type', INTEGER, server_default='0'),
    Column('claim_id', TEXT, nullable=True),
    Column('claim_hash', BINARY, nullable=True),
    Column('claim_name', TEXT, nullable=True),
    Column('channel_hash', BINARY, nullable=True),
    Column('reposted_claim_hash', BINARY, nullable=True),
)


TXI = Table(
    'txi', metadata,
    Column('tx_hash', BINARY, ForeignKey(TX.columns.tx_hash)),
    Column('txo_hash', BINARY, ForeignKey(TXO.columns.txo_hash), primary_key=True),
    Column('address', TEXT, ForeignKey(AccountAddress.columns.address)),
    Column('position', INTEGER),
)
