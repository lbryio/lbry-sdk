import os
import sqlite3


def do_migration(conf):
    db_path = os.path.join(conf.data_dir, "lbrynet.sqlite")
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()

    current_columns = []
    for col_info in cursor.execute("pragma table_info('file');").fetchall():
        current_columns.append(col_info[1])
    if 'bt_infohash' in current_columns:
        connection.close()
        print("already migrated")
        return

    cursor.executescript("""
        pragma foreign_keys=off;

        create table if not exists torrent (
            bt_infohash char(20) not null primary key,
            tracker text,
            length integer not null,
            name text not null
        );

        create table if not exists torrent_node ( -- BEP-0005
            bt_infohash char(20) not null references torrent,
            host text not null,
            port integer not null
        );

        create table if not exists torrent_tracker ( -- BEP-0012
            bt_infohash char(20) not null references torrent,
            tracker text not null
        );

        create table if not exists torrent_http_seed ( -- BEP-0017
            bt_infohash char(20) not null references torrent,
            http_seed text not null
        );

        create table if not exists new_file (
            stream_hash char(96) references stream,
            bt_infohash char(20) references torrent,
            file_name text,
            download_directory text,
            blob_data_rate real not null,
            status text not null,
            saved_file integer not null,
            content_fee text,
            added_on integer not null
        );

        create table if not exists new_content_claim (
            stream_hash char(96) references stream,
            bt_infohash char(20) references torrent,
            claim_outpoint text unique not null references claim
        );

        insert into new_file (stream_hash, bt_infohash, file_name, download_directory, blob_data_rate, status,
            saved_file, content_fee, added_on) select
                stream_hash, NULL, file_name, download_directory, blob_data_rate, status, saved_file, content_fee,
                added_on
            from file;

        insert or ignore into new_content_claim (stream_hash, bt_infohash, claim_outpoint)
            select stream_hash, NULL, claim_outpoint from content_claim;

        drop table file;
        drop table content_claim;
        alter table new_file rename to file;
        alter table new_content_claim rename to content_claim;

        pragma foreign_keys=on;
    """)

    connection.commit()
    connection.close()
