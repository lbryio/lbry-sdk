#! python

import os
import shutil
import rocksdb
import tempfile
import logging

log = logging.getLogger()
log.addHandler(logging.StreamHandler())
log.setLevel(logging.INFO)

def _main(db_loc):
    opts = rocksdb.Options(create_if_missing=True)
    db = rocksdb.DB(os.path.join(db_loc, "test"), opts)
    secondary_location = os.path.join(db_loc, "secondary")
    secondary = rocksdb.DB(
        os.path.join(db_loc, "test"),
        rocksdb.Options(create_if_missing=True, max_open_files=-1),
        secondary_name=secondary_location
    )
    try:
        assert secondary.get(b"a") is None
        db.put(b"a", b"b")
        assert db.get(b"a") == b"b"
        assert secondary.get(b"a") is None

        secondary.try_catch_up_with_primary()
        assert secondary.get(b"a") == b"b"
    finally:
        secondary.close()
        db.close()


def main():
    db_dir = tempfile.mkdtemp()
    try:
        _main(db_dir)
        log.info("rocksdb %s (%s) works!", rocksdb.__version__, rocksdb.ROCKSDB_VERSION)
    except:
        log.exception("boom")
    finally:
        shutil.rmtree(db_dir)


if __name__ == "__main__":
    main()
