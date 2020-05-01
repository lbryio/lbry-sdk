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
    Column('chain', Integer),
    Column('pubkey', LargeBinary),
    Column('chain_code', LargeBinary),
    Column('n', Integer),
    Column('depth', Integer),
)


Block = Table(
    'block', metadata,
    Column('block_hash', LargeBinary, primary_key=True),
    Column('previous_hash', LargeBinary),
    Column('file_number', SmallInteger),
    Column('height', Integer),
    Column('block_filter', LargeBinary, nullable=True)
)


TX = Table(
    'tx', metadata,
    Column('block_hash', LargeBinary, nullable=True),
    Column('tx_hash', LargeBinary, primary_key=True),
    Column('raw', LargeBinary),
    Column('height', Integer),
    Column('position', SmallInteger),
    Column('is_verified', Boolean, server_default='FALSE'),
    Column('purchased_claim_hash', LargeBinary, nullable=True),
    Column('day', Integer, nullable=True),
    Column('tx_filter', LargeBinary, nullable=True)
)


TXO = Table(
    'txo', metadata,
    Column('tx_hash', LargeBinary, ForeignKey(TX.columns.tx_hash)),
    Column('txo_hash', LargeBinary, primary_key=True),
    Column('address', Text),
    Column('position', Integer),
    Column('amount', BigInteger),
    Column('script_offset', BigInteger),
    Column('script_length', BigInteger),
    Column('is_reserved', Boolean, server_default='0'),
    Column('txo_type', Integer, server_default='0'),
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
    Column('position', Integer),
)

txi_join_account = TXI.join(AccountAddress, TXI.columns.address == AccountAddress.columns.address)


Claim = Table(
    'claim', metadata,
    Column('claim_hash', LargeBinary, primary_key=True),
    Column('claim_name', Text),
    Column('txo_hash', LargeBinary, ForeignKey(TXO.columns.txo_hash)),
    Column('amount', BigInteger),
    Column('channel_hash', LargeBinary, nullable=True),
    Column('effective_amount', BigInteger, server_default='0'),
    Column('reposted_claim_hash', LargeBinary, nullable=True),
    Column('activation_height', Integer, server_default='0'),
    Column('expiration_height', Integer, server_default='0'),
)


Tag = Table(
    'tag', metadata,
    Column('claim_hash', LargeBinary),
    Column('tag', Text),
)


Claimtrie = Table(
    'claimtrie', metadata,
    Column('normalized', Text, primary_key=True),
    Column('claim_hash', LargeBinary, ForeignKey(Claim.columns.claim_hash)),
    Column('last_take_over_height', Integer),
)
