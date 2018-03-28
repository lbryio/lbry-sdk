import sqlite3
import os


def do_migration(db_dir):
    db_path = os.path.join(db_dir, "lbrynet.sqlite")
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    cursor.executescript("alter table blob add last_announced_time integer;")
    cursor.executescript("alter table blob add single_announce integer;")
    cursor.execute("update blob set next_announce_time=0")
    connection.commit()
    connection.close()
