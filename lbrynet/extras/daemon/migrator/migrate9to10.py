import sqlite3
import os


def do_migration(db_dir):
    db_path = os.path.join(db_dir, "lbrynet.sqlite")
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    cursor.executescript("ALTER TABLE claim ADD resolved_at int DEFAULT 0 NOT NULL;")
    connection.commit()
    connection.close()
