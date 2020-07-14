import logging

from sqlalchemy import table, bindparam, text, func, union
from sqlalchemy.future import select
from sqlalchemy.schema import CreateTable

from lbry.db.tables import Block as BlockTable, TX, TXO, TXI
from lbry.db.tables import (
    pg_add_tx_constraints_and_indexes,
    pg_add_txo_constraints_and_indexes,
    pg_add_txi_constraints_and_indexes,
)
from lbry.db.query_context import ProgressContext, event_emitter, context
from lbry.db.sync import set_input_addresses, update_spent_outputs
from lbry.blockchain.block import Block, create_block_filter
from lbry.blockchain.bcd_data_stream import BCDataStream

from .context import get_or_initialize_lbrycrd


log = logging.getLogger(__name__)


def get_best_block_height_for_file(file_number):
    return context().fetchone(
        select(func.coalesce(func.max(BlockTable.c.height), -1).label('height'))
        .where(BlockTable.c.file_number == file_number)
    )['height']


@event_emitter("blockchain.sync.blocks.file", "blocks", "txs", throttle=100)
def sync_block_file(
    file_number: int, start_height: int, txs: int, flush_size: int, p: ProgressContext
):
    chain = get_or_initialize_lbrycrd(p.ctx)
    new_blocks = chain.db.sync_get_blocks_in_file(file_number, start_height)
    if not new_blocks:
        return -1
    file_name = chain.get_block_file_name(file_number)
    p.start(len(new_blocks), txs, progress_id=file_number, label=file_name)
    block_file_path = chain.get_block_file_path(file_number)
    done_blocks = done_txs = 0
    last_block_processed, loader = -1, p.ctx.get_bulk_loader()
    with open(block_file_path, "rb") as fp:
        stream = BCDataStream(fp=fp)
        for done_blocks, block_info in enumerate(new_blocks, start=1):
            block_height = block_info["height"]
            fp.seek(block_info["data_offset"])
            block = Block.from_data_stream(stream, block_height, file_number)
            loader.add_block(block)
            if len(loader.txs) >= flush_size:
                done_txs += loader.flush(TX)
            p.step(done_blocks, done_txs)
            last_block_processed = block_height
            if p.ctx.stop_event.is_set():
                return last_block_processed
    if loader.txs:
        done_txs += loader.flush(TX)
        p.step(done_blocks, done_txs)
    return last_block_processed


@event_emitter("blockchain.sync.spends.main", "steps")
def sync_spends(initial_sync: bool, p: ProgressContext):
    if initial_sync:
        p.start(
            6 +
            len(pg_add_tx_constraints_and_indexes) +
            len(pg_add_txi_constraints_and_indexes) +
            len(pg_add_txo_constraints_and_indexes)
        )
        for constraint in pg_add_tx_constraints_and_indexes:
            if p.ctx.is_postgres:
                p.ctx.execute(text(constraint))
            p.step()
        # A. Update TXIs to have the address of TXO they are spending.
        # 1. txi table reshuffling
        p.ctx.execute(text("ALTER TABLE txi RENAME TO old_txi;"))
        p.ctx.execute(CreateTable(TXI, include_foreign_key_constraints=[]))
        if p.ctx.is_postgres:
            p.ctx.execute(text("ALTER TABLE txi DROP CONSTRAINT txi_pkey;"))
        p.step()
        # 2. insert
        old_txi = table("old_txi", *(c.copy() for c in TXI.columns))  # pylint: disable=not-an-iterable
        columns = [c for c in old_txi.columns if c.name != "address"] + [TXO.c.address]
        join_txi_on_txo = old_txi.join(TXO, old_txi.c.txo_hash == TXO.c.txo_hash)
        select_txis = select(*columns).select_from(join_txi_on_txo)
        insert_txis = TXI.insert().from_select(columns, select_txis)
        p.ctx.execute(insert_txis)
        p.step()
        # 3. drop old txi and vacuum
        p.ctx.execute(text("DROP TABLE old_txi;"))
        if p.ctx.is_postgres:
            p.ctx.execute_notx(text("VACUUM ANALYZE txi;"))
        p.step()
        for constraint in pg_add_txi_constraints_and_indexes:
            if p.ctx.is_postgres:
                p.ctx.execute(text(constraint))
            p.step()
        # B. Update TXOs to have the height at which they were spent (if they were).
        # 4. txo table reshuffling
        p.ctx.execute(text("ALTER TABLE txo RENAME TO old_txo;"))
        p.ctx.execute(CreateTable(TXO, include_foreign_key_constraints=[]))
        if p.ctx.is_postgres:
            p.ctx.execute(text("ALTER TABLE txo DROP CONSTRAINT txo_pkey;"))
        p.step()
        # 5. insert
        old_txo = table("old_txo", *(c.copy() for c in TXO.columns))  # pylint: disable=not-an-iterable
        columns = [c for c in old_txo.columns if c.name != "spent_height"]
        insert_columns = columns + [TXO.c.spent_height]
        select_columns = columns + [func.coalesce(TXI.c.height, 0).label("spent_height")]
        join_txo_on_txi = old_txo.join(TXI, old_txo.c.txo_hash == TXI.c.txo_hash, isouter=True)
        select_txos = select(*select_columns).select_from(join_txo_on_txi)
        insert_txos = TXO.insert().from_select(insert_columns, select_txos)
        p.ctx.execute(insert_txos)
        p.step()
        # 6. drop old txo
        p.ctx.execute(text("DROP TABLE old_txo;"))
        if p.ctx.is_postgres:
            p.ctx.execute_notx(text("VACUUM ANALYZE txo;"))
        p.step()
        for constraint in pg_add_txo_constraints_and_indexes:
            if p.ctx.is_postgres:
                p.ctx.execute(text(constraint))
            p.step()
    else:
        p.start(3)
        # 1. Update spent TXOs setting spent_height
        update_spent_outputs(p.ctx)
        p.step()
        # 2. Update TXIs to have the address of TXO they are spending.
        set_input_addresses(p.ctx)
        p.step()
        # 3. Update visibility map, which speeds up index-only scans.
        if p.ctx.is_postgres:
            p.ctx.execute_notx(text("VACUUM txo;"))
        p.step()


@event_emitter("blockchain.sync.filter.generate", "blocks")
def sync_block_filters(p: ProgressContext):
    blocks = []
    all_filters = []
    all_addresses = []
    for block in get_blocks_without_filters():
        addresses = {
            p.ctx.ledger.address_to_hash160(r["address"])
            for r in get_block_tx_addresses(block_hash=block["block_hash"])
        }
        all_addresses.extend(addresses)
        block_filter = create_block_filter(addresses)
        all_filters.append(block_filter)
        blocks.append({"pk": block["block_hash"], "block_filter": block_filter})
    p.ctx.execute(
        BlockTable.update().where(BlockTable.c.block_hash == bindparam("pk")), blocks
    )


def get_blocks_without_filters():
    return context().fetchall(
        select(BlockTable.c.block_hash)
        .where(BlockTable.c.block_filter.is_(None))
    )


def get_block_tx_addresses(block_hash=None, tx_hash=None):
    if block_hash is not None:
        constraint = (TX.c.block_hash == block_hash)
    elif tx_hash is not None:
        constraint = (TX.c.tx_hash == tx_hash)
    else:
        raise ValueError('block_hash or tx_hash must be provided.')
    return context().fetchall(
        union(
            select(TXO.c.address).select_from(TXO.join(TX))
            .where((TXO.c.address.isnot_(None)) & constraint),
            select(TXI.c.address).select_from(TXI.join(TX))
            .where((TXI.c.address.isnot_(None)) & constraint),
        )
    )
