import sqlite3
import os
import binascii


def do_migration(conf):
    db_path = os.path.join(conf.data_dir, "lbrynet.sqlite")
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()

    current_columns = []
    for col_info in cursor.execute("pragma table_info('file');").fetchall():
        current_columns.append(col_info[1])
    if 'content_fee' in current_columns or 'saved_file' in current_columns:
        connection.close()
        print("already migrated")
        return

    cursor.execute(
        "pragma foreign_keys=off;"
    )

    cursor.execute("""
        create table if not exists new_file (
            stream_hash text primary key not null references stream,
            file_name text,
            download_directory text,
            blob_data_rate real not null,
            status text not null,
            saved_file integer not null,
            content_fee text
        );
    """)
    for (stream_hash, file_name, download_dir, data_rate, status) in cursor.execute("select * from file").fetchall():
        saved_file = 0
        if download_dir != '{stream}' and file_name != '{stream}':
            try:
                if os.path.isfile(os.path.join(binascii.unhexlify(download_dir).decode(),
                                  binascii.unhexlify(file_name).decode())):
                    saved_file = 1
                else:
                    download_dir, file_name = None, None
            except Exception:
                download_dir, file_name = None, None
        else:
            download_dir, file_name = None, None
        cursor.execute(
            "insert into new_file values (?, ?, ?, ?, ?, ?, NULL)",
            (stream_hash, file_name, download_dir, data_rate, status, saved_file)
        )
    cursor.execute("drop table file")
    cursor.execute("alter table new_file rename to file")
    connection.commit()
    connection.close()
