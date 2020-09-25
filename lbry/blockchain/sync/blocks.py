import logging
from binascii import hexlify, unhexlify
from typing import Tuple, List

from sqlalchemy import table, text, func, union, between
from sqlalchemy.future import select
from sqlalchemy.schema import CreateTable

from lbry.db.tables import (
    Block as BlockTable, BlockFilter, BlockGroupFilter,
    TX, TXFilter, MempoolFilter, TXO, TXI, Claim, Tag, Support
)
from lbry.db.tables import (
    pg_add_block_constraints_and_indexes,
    pg_add_block_filter_constraints_and_indexes,
    pg_add_tx_constraints_and_indexes,
    pg_add_tx_filter_constraints_and_indexes,
    pg_add_txo_constraints_and_indexes,
    pg_add_txi_constraints_and_indexes,
)
from lbry.db.query_context import ProgressContext, event_emitter, context
from lbry.db.sync import set_input_addresses, update_spent_outputs
from lbry.blockchain.transaction import Transaction
from lbry.blockchain.block import Block, create_address_filter
from lbry.blockchain.bcd_data_stream import BCDataStream

from .context import get_or_initialize_lbrycrd
from .filter_builder import FilterBuilder


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


@event_emitter("blockchain.sync.blocks.indexes", "steps")
def blocks_constraints_and_indexes(p: ProgressContext):
    p.start(1 + len(pg_add_block_constraints_and_indexes))
    if p.ctx.is_postgres:
        p.ctx.execute_notx(text("VACUUM ANALYZE block;"))
    p.step()
    for constraint in pg_add_block_constraints_and_indexes:
        if p.ctx.is_postgres:
            p.ctx.execute(text(constraint))
        p.step()


@event_emitter("blockchain.sync.blocks.vacuum", "steps")
def blocks_vacuum(p: ProgressContext):
    p.start(1)
    if p.ctx.is_postgres:
        p.ctx.execute_notx(text("VACUUM block;"))
    p.step()


@event_emitter("blockchain.sync.spends.main", "steps")
def sync_spends(initial_sync: bool, p: ProgressContext):
    if initial_sync:
        p.start(
            7 +
            len(pg_add_tx_constraints_and_indexes) +
            len(pg_add_txi_constraints_and_indexes) +
            len(pg_add_txo_constraints_and_indexes)
        )
        # 1. tx table stuff
        if p.ctx.is_postgres:
            p.ctx.execute_notx(text("VACUUM ANALYZE tx;"))
        p.step()
        for constraint in pg_add_tx_constraints_and_indexes:
            if p.ctx.is_postgres:
                p.ctx.execute(text(constraint))
            p.step()
        # A. Update TXIs to have the address of TXO they are spending.
        # 2. txi table reshuffling
        p.ctx.execute(text("ALTER TABLE txi RENAME TO old_txi;"))
        p.ctx.execute(CreateTable(TXI, include_foreign_key_constraints=[]))
        if p.ctx.is_postgres:
            p.ctx.execute(text("ALTER TABLE txi DROP CONSTRAINT txi_pkey;"))
        p.step()
        # 3. insert
        old_txi = table("old_txi", *(c.copy() for c in TXI.columns))  # pylint: disable=not-an-iterable
        columns = [c for c in old_txi.columns if c.name != "address"] + [TXO.c.address]
        join_txi_on_txo = old_txi.join(TXO, old_txi.c.txo_hash == TXO.c.txo_hash)
        select_txis = select(*columns).select_from(join_txi_on_txo)
        insert_txis = TXI.insert().from_select(columns, select_txis)
        p.ctx.execute(insert_txis)
        p.step()
        # 4. drop old txi and vacuum
        p.ctx.execute(text("DROP TABLE old_txi;"))
        if p.ctx.is_postgres:
            p.ctx.execute_notx(text("VACUUM ANALYZE txi;"))
        p.step()
        for constraint in pg_add_txi_constraints_and_indexes:
            if p.ctx.is_postgres:
                p.ctx.execute(text(constraint))
            p.step()
        # B. Update TXOs to have the height at which they were spent (if they were).
        # 5. txo table reshuffling
        p.ctx.execute(text("ALTER TABLE txo RENAME TO old_txo;"))
        p.ctx.execute(CreateTable(TXO, include_foreign_key_constraints=[]))
        if p.ctx.is_postgres:
            p.ctx.execute(text("ALTER TABLE txo DROP CONSTRAINT txo_pkey;"))
        p.step()
        # 6. insert
        old_txo = table("old_txo", *(c.copy() for c in TXO.columns))  # pylint: disable=not-an-iterable
        columns = [c for c in old_txo.columns if c.name != "spent_height"]
        insert_columns = columns + [TXO.c.spent_height]
        select_columns = columns + [func.coalesce(TXI.c.height, 0).label("spent_height")]
        join_txo_on_txi = old_txo.join(TXI, old_txo.c.txo_hash == TXI.c.txo_hash, isouter=True)
        select_txos = select(*select_columns).select_from(join_txo_on_txi)
        insert_txos = TXO.insert().from_select(insert_columns, select_txos)
        p.ctx.execute(insert_txos)
        p.step()
        # 7. drop old txo
        p.ctx.execute(text("DROP TABLE old_txo;"))
        if p.ctx.is_postgres:
            p.ctx.execute_notx(text("VACUUM ANALYZE txo;"))
        p.step()
        for constraint in pg_add_txo_constraints_and_indexes:
            if p.ctx.is_postgres:
                p.ctx.execute(text(constraint))
            p.step()
    else:
        p.start(5)
        # 1. Update spent TXOs setting spent_height
        update_spent_outputs(p.ctx)
        p.step()
        # 2. Update TXIs to have the address of TXO they are spending.
        set_input_addresses(p.ctx)
        p.step()
        # 3. Update tx visibility map, which speeds up index-only scans.
        if p.ctx.is_postgres:
            p.ctx.execute_notx(text("VACUUM tx;"))
        p.step()
        # 4. Update txi visibility map, which speeds up index-only scans.
        if p.ctx.is_postgres:
            p.ctx.execute_notx(text("VACUUM txi;"))
        p.step()
        # 4. Update txo visibility map, which speeds up index-only scans.
        if p.ctx.is_postgres:
            p.ctx.execute_notx(text("VACUUM txo;"))
        p.step()


@event_emitter("blockchain.sync.mempool.clear", "txs")
def clear_mempool(p: ProgressContext):
    delete_all_the_things(-1, p)


@event_emitter("blockchain.sync.mempool.main", "txs")
def sync_mempool(p: ProgressContext) -> List[str]:
    chain = get_or_initialize_lbrycrd(p.ctx)
    mempool = chain.sync_run(chain.get_raw_mempool())
    current = [hexlify(r['tx_hash'][::-1]).decode() for r in p.ctx.fetchall(
        select(TX.c.tx_hash).where(TX.c.height < 0)
    )]
    loader = p.ctx.get_bulk_loader()
    added = []
    for txid in mempool:
        if txid not in current:
            raw_tx = chain.sync_run(chain.get_raw_transaction(txid))
            loader.add_transaction(
                None, Transaction(unhexlify(raw_tx), height=-1)
            )
            added.append(txid)
        if p.ctx.stop_event.is_set():
            return
    loader.flush(TX)
    return added


@event_emitter("blockchain.sync.filters.generate", "blocks", throttle=100)
def sync_filters(start, end, p: ProgressContext):
    fp = FilterBuilder(start, end)
    p.start((end-start)+1, progress_id=start, label=f"generate filters {start}-{end}")
    with p.ctx.connect_streaming() as c:
        loader = p.ctx.get_bulk_loader()

        tx_hash, height, addresses, last_added = None, None, set(), None
        address_to_hash = p.ctx.ledger.address_to_hash160
        for row in c.execute(get_block_tx_addresses_sql(*fp.query_heights)):
            if tx_hash != row.tx_hash:
                if tx_hash is not None:
                    last_added = tx_hash
                    fp.add(tx_hash, height, addresses)
                tx_hash, height, addresses = row.tx_hash, row.height, set()
            addresses.add(address_to_hash(row.address))
        if all([last_added, tx_hash]) and last_added != tx_hash:  # pickup last tx
            fp.add(tx_hash, height, addresses)

        for tx_hash, height, addresses in fp.tx_filters:
            loader.add_transaction_filter(
                tx_hash, height, create_address_filter(list(addresses))
            )

        for height, addresses in fp.block_filters.items():
            loader.add_block_filter(
                height, create_address_filter(list(addresses))
            )

        for group_filter in fp.group_filters:
            for height, addresses in group_filter.groups.items():
                loader.add_group_filter(
                    height, group_filter.factor, create_address_filter(list(addresses))
                )

        p.add(loader.flush(BlockFilter))


@event_emitter("blockchain.sync.filters.indexes", "steps")
def filters_constraints_and_indexes(p: ProgressContext):
    constraints = (
        pg_add_tx_filter_constraints_and_indexes +
        pg_add_block_filter_constraints_and_indexes
    )
    p.start(2 + len(constraints))
    if p.ctx.is_postgres:
        p.ctx.execute_notx(text("VACUUM ANALYZE block_filter;"))
    p.step()
    if p.ctx.is_postgres:
        p.ctx.execute_notx(text("VACUUM ANALYZE tx_filter;"))
    p.step()
    for constraint in constraints:
        if p.ctx.is_postgres:
            p.ctx.execute(text(constraint))
        p.step()


@event_emitter("blockchain.sync.filters.vacuum", "steps")
def filters_vacuum(p: ProgressContext):
    p.start(2)
    if p.ctx.is_postgres:
        p.ctx.execute_notx(text("VACUUM block_filter;"))
    p.step()
    if p.ctx.is_postgres:
        p.ctx.execute_notx(text("VACUUM tx_filter;"))
    p.step()


def get_block_range_without_filters() -> Tuple[int, int]:
    sql = (
        select(
            func.coalesce(func.min(BlockTable.c.height), -1).label('start_height'),
            func.coalesce(func.max(BlockTable.c.height), -1).label('end_height'),
        )
        .select_from(
            BlockTable.join(BlockFilter, BlockTable.c.height == BlockFilter.c.height, isouter=True)
        )
        .where(BlockFilter.c.height.is_(None))
    )
    result = context().fetchone(sql)
    return result['start_height'], result['end_height']


def get_block_tx_addresses_sql(start_height, end_height):
    return union(
        select(TXO.c.tx_hash, TXO.c.height, TXO.c.address).where(
            (TXO.c.address.isnot(None)) & between(TXO.c.height, start_height, end_height)
        ),
        select(TXI.c.tx_hash, TXI.c.height, TXI.c.address).where(
            (TXI.c.address.isnot(None)) & between(TXI.c.height, start_height, end_height)
        ),
    ).order_by('height', 'tx_hash')


@event_emitter("blockchain.sync.rewind.main", "steps")
def rewind(height: int, p: ProgressContext):
    delete_all_the_things(height, p)


def delete_all_the_things(height: int, p: ProgressContext):
    def constrain(col):
        if height == -1:
            return col == -1
        return col >= height

    deletes = [
        BlockTable.delete().where(constrain(BlockTable.c.height)),
        TXI.delete().where(constrain(TXI.c.height)),
        TXO.delete().where(constrain(TXO.c.height)),
        TX.delete().where(constrain(TX.c.height)),
        Tag.delete().where(
            Tag.c.claim_hash.in_(
                select(Claim.c.claim_hash).where(constrain(Claim.c.height))
            )
        ),
        Claim.delete().where(constrain(Claim.c.height)),
        Support.delete().where(constrain(Support.c.height)),
        MempoolFilter.delete(),
    ]
    if height > 0:
        deletes.extend([
            BlockFilter.delete().where(BlockFilter.c.height >= height),
            # TODO: group and tx filters need where() clauses (below actually breaks things)
            BlockGroupFilter.delete(),
            TXFilter.delete(),
        ])
    for delete in p.iter(deletes):
        p.ctx.execute(delete)
