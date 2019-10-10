import sqlite3
import os
import time


def do_migration(conf):
    db_path = os.path.join(conf.data_dir, 'lbrynet.sqlite')
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    current_columns = []
    for col_info in cursor.execute("pragma table_info('file');").fetchall():
        current_columns.append(col_info[1])

    if 'added_at' in current_columns:
        connection.close()
        print('already migrated')
        return

    # follow 12 step schema change procedure
    cursor.execute("pragma foreign_keys=off")

    # we don't have any indexes, views or triggers, so step 3 is skipped.
    cursor.execute("drop table if exists new_file")
    cursor.execute("""
        create table if not exists new_file (
            stream_hash         text    not null    primary key     references stream,
            file_name           text,
            download_directory  text,
            blob_data_rate      text    not null,
            status              text    not null,
            saved_file          integer not null,
            content_fee         text,
            added_at            integer not null
        );


    """)

    # step 5: transfer content from old to new
    select = "select * from file"
    for (stream_hash, file_name, download_dir, data_rate, blob_rate, status, saved_file, fee) \
            in cursor.execute(select).fetchall():
        added_at = int(time.time())
        cursor.execute(
            "insert into new_file values (?, ?, ?, ?, ?, ?, ?, ?)",
            (stream_hash, file_name, download_dir, data_rate, blob_rate, status, saved_file, fee, added_at)
        )

    # step 6: drop old table
    cursor.execute("drop table file")

    # step 7: rename new table to old table
    cursor.execute("alter table new_file rename to file")

    # step 8: we aren't using indexes, views or triggers so skip
    # step 9: no views so skip
    # step 10: foreign key check
    cursor.execute("pragma foreign_key_check;")

    # step 11: commit transaction
    connection.commit()

    # step 12: re-enable foreign keys
    connection.execute("pragma foreign_keys=on;")

    # done :)
    connection.close()
