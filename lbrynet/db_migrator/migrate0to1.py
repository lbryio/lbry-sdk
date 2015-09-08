import sqlite3
import unqlite
import leveldb
import shutil
import os
import logging
import json


log = logging.getLogger(__name__)


known_dbs = ['lbryfile_desc.db', 'lbryfiles.db', 'valuable_blobs.db', 'blobs.db',
             'lbryfile_blob.db', 'lbryfile_info.db', 'settings.db', 'blind_settings.db',
             'blind_peers.db', 'blind_info.db', 'lbryfile_info.db', 'lbryfile_manager.db',
             'live_stream.db', 'stream_info.db', 'stream_blob.db', 'stream_desc.db']


def do_move(from_dir, to_dir):
    for known_db in known_dbs:
        known_db_path = os.path.join(from_dir, known_db)
        if os.path.exists(known_db_path):
            log.debug("Moving %s to %s",
                      os.path.abspath(known_db_path),
                      os.path.abspath(os.path.join(to_dir, known_db)))
            shutil.move(known_db_path, os.path.join(to_dir, known_db))
        else:
            log.debug("Did not find %s", os.path.abspath(known_db_path))


def do_migration(db_dir):
    old_dir = os.path.join(db_dir, "_0_to_1_old")
    new_dir = os.path.join(db_dir, "_0_to_1_new")
    try:
        log.info("Moving dbs from the real directory to %s", os.path.abspath(old_dir))
        os.makedirs(old_dir)
        do_move(db_dir, old_dir)
    except:
        log.error("An error occurred moving the old db files.")
        raise
    try:
        log.info("Creating the new directory in %s", os.path.abspath(new_dir))
        os.makedirs(new_dir)

    except:
        log.error("An error occurred creating the new directory.")
        raise
    try:
        log.info("Doing the migration")
        migrate_blob_db(old_dir, new_dir)
        migrate_lbryfile_db(old_dir, new_dir)
        migrate_livestream_db(old_dir, new_dir)
        migrate_ptc_db(old_dir, new_dir)
        migrate_lbryfile_manager_db(old_dir, new_dir)
        migrate_settings_db(old_dir, new_dir)
        migrate_repeater_db(old_dir, new_dir)
        log.info("Migration succeeded")
    except:
        log.error("An error occurred during the migration. Restoring.")
        do_move(old_dir, db_dir)
        raise
    try:
        log.info("Moving dbs in the new directory to the real directory")
        do_move(new_dir, db_dir)
        db_revision = open(os.path.join(db_dir, 'db_revision'), mode='w+')
        db_revision.write("1")
        db_revision.close()
        os.rmdir(new_dir)
    except:
        log.error("An error occurred moving the new db files.")
        raise
    return old_dir


def migrate_blob_db(old_db_dir, new_db_dir):
    old_blob_db_path = os.path.join(old_db_dir, "blobs.db")
    if not os.path.exists(old_blob_db_path):
        return True

    old_db = leveldb.LevelDB(old_blob_db_path)
    new_db_conn = sqlite3.connect(os.path.join(new_db_dir, "blobs.db"))
    c = new_db_conn.cursor()
    c.execute("create table if not exists blobs (" +
              "    blob_hash text primary key, " +
              "    blob_length integer, " +
              "    last_verified_time real, " +
              "    next_announce_time real"
              ")")
    new_db_conn.commit()
    c = new_db_conn.cursor()
    for blob_hash, blob_info in old_db.RangeIter():
        blob_length, verified_time, announce_time = json.loads(blob_info)
        c.execute("insert into blobs values (?, ?, ?, ?)",
                  (blob_hash, blob_length, verified_time, announce_time))
    new_db_conn.commit()
    new_db_conn.close()


def migrate_lbryfile_db(old_db_dir, new_db_dir):
    old_lbryfile_db_path = os.path.join(old_db_dir, "lbryfiles.db")
    if not os.path.exists(old_lbryfile_db_path):
        return True

    stream_info_db = leveldb.LevelDB(os.path.join(old_db_dir, "lbryfile_info.db"))
    stream_blob_db = leveldb.LevelDB(os.path.join(old_db_dir, "lbryfile_blob.db"))
    stream_desc_db = leveldb.LevelDB(os.path.join(old_db_dir, "lbryfile_desc.db"))

    db_conn = sqlite3.connect(os.path.join(new_db_dir, "lbryfile_info.db"))
    c = db_conn.cursor()
    c.execute("create table if not exists lbry_files (" +
              "    stream_hash text primary key, " +
              "    key text, " +
              "    stream_name text, " +
              "    suggested_file_name text" +
              ")")
    c.execute("create table if not exists lbry_file_blobs (" +
              "    blob_hash text, " +
              "    stream_hash text, " +
              "    position integer, " +
              "    iv text, " +
              "    length integer, " +
              "    foreign key(stream_hash) references lbry_files(stream_hash)" +
              ")")
    c.execute("create table if not exists lbry_file_descriptors (" +
              "    sd_blob_hash TEXT PRIMARY KEY, " +
              "    stream_hash TEXT, " +
              "    foreign key(stream_hash) references lbry_files(stream_hash)" +
              ")")
    db_conn.commit()
    c = db_conn.cursor()
    for stream_hash, stream_info in stream_info_db.RangeIter():
        key, name, suggested_file_name = json.loads(stream_info)
        c.execute("insert into lbry_files values (?, ?, ?, ?)",
                  (stream_hash, key, name, suggested_file_name))
    db_conn.commit()
    c = db_conn.cursor()
    for blob_hash_stream_hash, blob_info in stream_blob_db.RangeIter():
        b_h, s_h = json.loads(blob_hash_stream_hash)
        position, iv, length = json.loads(blob_info)
        c.execute("insert into lbry_file_blobs values (?, ?, ?, ?, ?)",
                  (b_h, s_h, position, iv, length))
    db_conn.commit()
    c = db_conn.cursor()
    for sd_blob_hash, stream_hash in stream_desc_db.RangeIter():
        c.execute("insert into lbry_file_descriptors values (?, ?)",
                  (sd_blob_hash, stream_hash))
    db_conn.commit()
    db_conn.close()


def migrate_livestream_db(old_db_dir, new_db_dir):
    old_db_path = os.path.join(old_db_dir, "stream_info.db")
    if not os.path.exists(old_db_path):
        return True
    stream_info_db = leveldb.LevelDB(os.path.join(old_db_dir, "stream_info.db"))
    stream_blob_db = leveldb.LevelDB(os.path.join(old_db_dir, "stream_blob.db"))
    stream_desc_db = leveldb.LevelDB(os.path.join(old_db_dir, "stream_desc.db"))

    db_conn = sqlite3.connect(os.path.join(new_db_dir, "live_stream.db"))

    c = db_conn.cursor()

    c.execute("create table if not exists live_streams (" +
              "    stream_hash text primary key, " +
              "    public_key text, " +
              "    key text, " +
              "    stream_name text, " +
              "    next_announce_time real" +
              ")")
    c.execute("create table if not exists live_stream_blobs (" +
              "    blob_hash text, " +
              "    stream_hash text, " +
              "    position integer, " +
              "    revision integer, " +
              "    iv text, " +
              "    length integer, " +
              "    signature text, " +
              "    foreign key(stream_hash) references live_streams(stream_hash)" +
              ")")
    c.execute("create table if not exists live_stream_descriptors (" +
              "    sd_blob_hash TEXT PRIMARY KEY, " +
              "    stream_hash TEXT, " +
              "    foreign key(stream_hash) references live_streams(stream_hash)" +
              ")")

    db_conn.commit()

    c = db_conn.cursor()
    for stream_hash, stream_info in stream_info_db.RangeIter():
        public_key, key, name, next_announce_time = json.loads(stream_info)
        c.execute("insert into live_streams values (?, ?, ?, ?, ?)",
                  (stream_hash, public_key, key, name, next_announce_time))
    db_conn.commit()
    c = db_conn.cursor()
    for blob_hash_stream_hash, blob_info in stream_blob_db.RangeIter():
        b_h, s_h = json.loads(blob_hash_stream_hash)
        position, revision, iv, length, signature = json.loads(blob_info)
        c.execute("insert into live_stream_blobs values (?, ?, ?, ?, ?, ?, ?)",
                  (b_h, s_h, position, revision, iv, length, signature))
    db_conn.commit()
    c = db_conn.cursor()
    for sd_blob_hash, stream_hash in stream_desc_db.RangeIter():
        c.execute("insert into live_stream_descriptors values (?, ?)",
                  (sd_blob_hash, stream_hash))
    db_conn.commit()
    db_conn.close()


def migrate_ptc_db(old_db_dir, new_db_dir):
    old_db_path = os.path.join(old_db_dir, "ptcwallet.db")
    if not os.path.exists(old_db_path):
        return True
    old_db = leveldb.LevelDB(old_db_path)
    try:
        p_key = old_db.Get("private_key")
        new_db = unqlite.UnQLite(os.path.join(new_db_dir, "ptcwallet.db"))
        new_db['private_key'] = p_key
    except KeyError:
        pass


def migrate_lbryfile_manager_db(old_db_dir, new_db_dir):
    old_db_path = os.path.join(old_db_dir, "lbryfiles.db")
    if not os.path.exists(old_db_path):
        return True
    old_db = leveldb.LevelDB(old_db_path)
    new_db = sqlite3.connect(os.path.join(new_db_dir, "lbryfile_info.db"))
    c = new_db.cursor()
    c.execute("create table if not exists lbry_file_options (" +
              "    blob_data_rate real, " +
              "    status text," +
              "    stream_hash text,"
              "    foreign key(stream_hash) references lbry_files(stream_hash)" +
              ")")
    new_db.commit()
    LBRYFILE_STATUS = "t"
    LBRYFILE_OPTIONS = "o"
    c = new_db.cursor()
    for k, v in old_db.RangeIter():
        key_type, stream_hash = json.loads(k)
        if key_type == LBRYFILE_STATUS:
            try:
                rate = json.loads(old_db.Get(json.dumps((LBRYFILE_OPTIONS, stream_hash))))[0]
            except KeyError:
                rate = None
            c.execute("insert into lbry_file_options values (?, ?, ?)",
                      (rate, v, stream_hash))
    new_db.commit()
    new_db.close()


def migrate_settings_db(old_db_dir, new_db_dir):
    old_settings_db_path = os.path.join(old_db_dir, "settings.db")
    if not os.path.exists(old_settings_db_path):
        return True
    old_db = leveldb.LevelDB(old_settings_db_path)
    new_db = unqlite.UnQLite(os.path.join(new_db_dir, "settings.db"))
    for k, v in old_db.RangeIter():
        new_db[k] = v


def migrate_repeater_db(old_db_dir, new_db_dir):
    old_repeater_db_path = os.path.join(old_db_dir, "valuable_blobs.db")
    if not os.path.exists(old_repeater_db_path):
        return True
    old_db = leveldb.LevelDB(old_repeater_db_path)
    info_db = sqlite3.connect(os.path.join(new_db_dir, "blind_info.db"))
    peer_db = sqlite3.connect(os.path.join(new_db_dir, "blind_peers.db"))
    unql_db = unqlite.UnQLite(os.path.join(new_db_dir, "blind_settings.db"))
    BLOB_INFO_TYPE = 'b'
    SETTING_TYPE = 's'
    PEER_TYPE = 'p'
    info_c = info_db.cursor()
    info_c.execute("create table if not exists valuable_blobs (" +
                   "    blob_hash text primary key, " +
                   "    blob_length integer, " +
                   "    reference text, " +
                   "    peer_host text, " +
                   "    peer_port integer, " +
                   "    peer_score text" +
                   ")")
    info_db.commit()
    peer_c = peer_db.cursor()
    peer_c.execute("create table if not exists approved_peers (" +
                   "    ip_address text, " +
                   "    port integer" +
                   ")")
    peer_db.commit()
    info_c = info_db.cursor()
    peer_c = peer_db.cursor()
    for k, v in old_db.RangeIter():
        key_type, key_rest = json.loads(k)
        if key_type == PEER_TYPE:
            host, port = key_rest
            peer_c.execute("insert into approved_peers values (?, ?)",
                           (host, port))
        elif key_type == SETTING_TYPE:
            unql_db[key_rest] = v
        elif key_type == BLOB_INFO_TYPE:
            blob_hash = key_rest
            length, reference, peer_host, peer_port, peer_score = json.loads(v)
            info_c.execute("insert into valuable_blobs values (?, ?, ?, ?, ?, ?)",
                           (blob_hash, length, reference, peer_host, peer_port, peer_score))
    info_db.commit()
    peer_db.commit()
    info_db.close()
    peer_db.close()