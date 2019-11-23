import os
import sqlite3


def do_migration(conf):
    db_path = os.path.join(conf.data_dir, "lbrynet.sqlite")
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()

    cursor.executescript("""
        create table if not exists peer (
            node_id char(96) not null primary key,
            address text not null,
            udp_port integer not null,
            tcp_port integer,
            unique (address, udp_port)
        );
    """)

    connection.commit()
    connection.close()
