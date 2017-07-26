import sqlite3
import os
import logging

log = logging.getLogger(__name__)


def do_migration(db_dir):
    log.info("Doing the migration")
    migrate_blobs_db(db_dir)
    log.info("Migration succeeded")


def migrate_blobs_db(db_dir):
    """
    We migrate the blobs.db used in BlobManager to have a "should_announce" column,
    and set this to True for blobs that are sd_hash's or head blobs (first blob in stream)
    We also add a "last_announce_time" column for when the blob as last announced
    for debugging purposes
    """

    blobs_db = os.path.join(db_dir, "blobs.db")
    lbryfile_info_db = os.path.join(db_dir, 'lbryfile_info.db')

    # skip migration on fresh installs
    if not os.path.isfile(blobs_db) and not os.path.isfile(lbryfile_info_db):
        return

    # if blobs.db doesn't exist, skip migration
    if not os.path.isfile(blobs_db):
        log.error("blobs.db was not found but lbryfile_info.db was found, skipping migration")
        return

    blobs_db_file = sqlite3.connect(blobs_db)
    blobs_db_cursor = blobs_db_file.cursor()

    # check if new columns exist (it shouldn't) and create it
    try:
        blobs_db_cursor.execute("SELECT should_announce FROM blobs")
    except sqlite3.OperationalError:
        blobs_db_cursor.execute(
            "ALTER TABLE blobs ADD COLUMN should_announce integer NOT NULL DEFAULT 0")
    else:
        log.warn("should_announce already exists somehow, proceeding anyways")

    try:
        blobs_db_cursor.execute("SELECT last_announce_time FROM blobs")
    except sqlite3.OperationalError:
        blobs_db_cursor.execute("ALTER TABLE blobs ADD COLUMN last_announce_time")
    else:
        log.warn("last_announce_time already exist somehow, proceeding anyways")


    # if lbryfile_info.db doesn't exist, skip marking blobs as should_announce = True
    if not os.path.isfile(lbryfile_info_db):
        log.error("lbryfile_info.db was not found, skipping check for should_announce")
        return

    lbryfile_info_file = sqlite3.connect(lbryfile_info_db)
    lbryfile_info_cursor = lbryfile_info_file.cursor()

    # find blobs that are stream descriptors
    lbryfile_info_cursor.execute('SELECT * FROM lbry_file_descriptors')
    descriptors = lbryfile_info_cursor.fetchall()
    should_announce_blob_hashes = []
    for d in descriptors:
        sd_blob_hash = (d[0],)
        should_announce_blob_hashes.append(sd_blob_hash)

    # find blobs that are the first blob in a stream
    lbryfile_info_cursor.execute('SELECT * FROM lbry_file_blobs WHERE position = 0')
    blobs = lbryfile_info_cursor.fetchall()
    head_blob_hashes = []
    for b in blobs:
        blob_hash = (b[0],)
        should_announce_blob_hashes.append(blob_hash)

    # now mark them as should_announce = True
    blobs_db_cursor.executemany('UPDATE blobs SET should_announce=1 WHERE blob_hash=?',
                                should_announce_blob_hashes)

    # Now run some final checks here to make sure migration succeeded
    try:
        blobs_db_cursor.execute("SELECT should_announce FROM blobs")
    except sqlite3.OperationalError:
        raise Exception('Migration failed, cannot find should_announce')

    try:
        blobs_db_cursor.execute("SELECT last_announce_time FROM blobs")
    except sqlite3.OperationalError:
        raise Exception('Migration failed, cannot find last_announce_time')

    blobs_db_cursor.execute("SELECT * FROM blobs WHERE should_announce=1")
    blobs = blobs_db_cursor.fetchall()
    if len(blobs) != len(should_announce_blob_hashes):
        log.error("Some how not all blobs were marked as announceable")

    blobs_db_file.commit()


