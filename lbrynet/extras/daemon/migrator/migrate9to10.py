import sqlite3
import os


def do_migration(conf):
    db_path = os.path.join(conf.data_dir, "lbrynet.sqlite")
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()

    query = "select stream_hash, sd_hash from main.stream"
    for stream_hash, sd_hash in cursor.execute(query):
        head_blob_hash = cursor.execute(
            "select blob_hash from stream_blob where position = 0 and stream_hash = ?",
            (stream_hash,)
        ).fetchone()
        if not head_blob_hash:
            continue
        cursor.execute("update blob set should_announce=1 where blob_hash in (?, ?)", (sd_hash, head_blob_hash[0],))
    connection.commit()
    connection.close()
