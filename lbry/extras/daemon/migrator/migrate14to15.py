import os
import sqlite3


def do_migration(conf):
    db_path = os.path.join(conf.data_dir, "lbrynet.sqlite")
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()

    cursor.executescript("""
        alter table blob add column added_on integer not null default 0;
        alter table blob add column is_mine integer not null default 1;
    """)

    connection.commit()
    connection.close()
