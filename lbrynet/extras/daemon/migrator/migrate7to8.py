import sqlite3
import os


def do_migration(db_dir):
    db_path = os.path.join(db_dir, "lbrynet.sqlite")
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()

    cursor.executescript(
        """
        create table reflected_stream (
            sd_hash text not null,
            reflector_address text not null,
            timestamp integer,
            primary key (sd_hash, reflector_address)
        );
        """
    )
    connection.commit()
    connection.close()
