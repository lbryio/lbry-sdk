import os
import plyvel
from lbry.wallet.server.db.db import RocksDBStore


def main(db_dir: str):
    old_path = os.path.join(db_dir, 'lbry-leveldb')
    new_path = os.path.join(db_dir, 'lbry-rocksdb')

    old_db = plyvel.DB(
        old_path, create_if_missing=True, max_open_files=256,
        write_buffer_size=64 * 1024 * 1024,
        max_file_size=1024 * 1024 * 64, bloom_filter_bits=32
    )
    new_db = RocksDBStore(new_path, 64, 256)
    try:
        batch = []
        append_batch = batch.append
        cnt = 0
        for k, v in old_db.iterator():
            append_batch((k, v))
            cnt += 1
            if cnt % 100_000 == 0:
                with new_db.write_batch() as batch_write:
                    batch_put = batch_write.put
                    for item in batch:
                        batch_put(*item)
                batch.clear()
                print(f"flushed {cnt} key/value items")
    finally:
        old_db.close()
        new_db.close()


if __name__ == "__main__":
    main('/mnt/sdb/wallet_server/_data/')
