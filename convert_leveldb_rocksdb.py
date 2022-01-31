import os
import plyvel
from lbry.wallet.server.db.prefixes import HubDB, DB_PREFIXES


def main(db_dir: str):
    old_path = os.path.join(db_dir, 'lbry-leveldb')
    new_path = os.path.join(db_dir, 'lbry-rocksdb')
    old_db = plyvel.DB(
        old_path, create_if_missing=False, max_open_files=64,
    )
    db = HubDB(new_path, max_open_files=64)
    try:

        for prefix, cf in db.column_families.items():
            cnt = 0
            for shard_int in range(2**8):
                shard_prefix = prefix + shard_int.to_bytes(1, byteorder='big')
                with db._db.write_batch() as batch:
                    batch_put = batch.put
                    with old_db.iterator(prefix=shard_prefix, fill_cache=False) as it:
                        cnt_batch = 0
                        for k, v in it:
                            batch_put((cf, k), v)
                            cnt += 1
                            cnt_batch += 1
                            if cnt % 100_000 == 0:
                                print(f"wrote {cnt} {DB_PREFIXES(prefix).name} items")
                            if cnt_batch % 1_000_000 == 0:
                                print(f"cnt_batch {cnt_batch} flushing 1m items")
                                db._db.write(batch)
                                batch.clear()

    finally:
        old_db.close()
        db.close()


if __name__ == "__main__":
    main('/mnt/sdb/wallet_server/_data/')
