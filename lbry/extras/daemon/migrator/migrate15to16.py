import os
import sqlite3


def do_migration(conf):
    db_path = os.path.join(conf.data_dir, "lbrynet.sqlite")
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()

    cursor.executescript("""
        update blob set should_announce=0
        where should_announce=1 and 
        blob.blob_hash in (select stream_blob.blob_hash from stream_blob where position=0);
    """)

    connection.commit()
    connection.close()
