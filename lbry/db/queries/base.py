from sqlalchemy import text, between
from sqlalchemy.future import select

from ..query_context import context
from ..tables import (
    SCHEMA_VERSION, metadata, Version,
    Claim, Support, Block, TX,
    pg_add_account_address_constraints_and_indexes
)


def execute(sql):
    return context().execute(text(sql))


def execute_sql_object(sql):
    return context().execute(sql)


def execute_fetchall(sql):
    return context().fetchall(text(sql))


def has_claims():
    return context().has_records(Claim)


def has_supports():
    return context().has_records(Support)


def get_best_block_height():
    return context().fetchmax(Block.c.height, -1)


def insert_block(block):
    context().get_bulk_loader().add_block(block).flush(return_row_count_for_table=None)


def get_block_headers(first, last=None):
    if last is not None:
        query = (
            select('*').select_from(Block)
            .where(between(Block.c.height, first, last))
            .order_by(Block.c.height)
        )
    else:
        query = select('*').select_from(Block).where(Block.c.height == first)
    return context().fetchall(query)


def insert_transaction(block_hash, tx):
    context().get_bulk_loader().add_transaction(block_hash, tx).flush(TX)


def check_version_and_create_tables():
    with context("db.connecting") as ctx:
        if ctx.has_table('version'):
            version = ctx.fetchone(select(Version.c.version).limit(1))
            if version and version['version'] == SCHEMA_VERSION:
                return
        metadata.drop_all(ctx.engine)
        metadata.create_all(ctx.engine)
        ctx.execute(Version.insert().values(version=SCHEMA_VERSION))
        for table in metadata.sorted_tables:
            disable_trigger_and_constraints(table.name)
        if ctx.is_postgres:
            for statement in pg_add_account_address_constraints_and_indexes:
                ctx.execute(text(statement))


def disable_trigger_and_constraints(table_name):
    ctx = context()
    if ctx.is_postgres:
        ctx.execute(text(f"ALTER TABLE {table_name} DISABLE TRIGGER ALL;"))
    if table_name in ('tag', 'stake', 'block_filter', 'mempool_filter'):
        return
    if ctx.is_postgres:
        ctx.execute(text(
            f"ALTER TABLE {table_name} DROP CONSTRAINT {table_name}_pkey CASCADE;"
        ))
