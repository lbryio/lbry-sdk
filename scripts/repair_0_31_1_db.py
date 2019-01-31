import os
import binascii
import sqlite3
from lbrynet.conf import Config


def main():
    conf = Config()
    db = sqlite3.connect(os.path.join(conf.data_dir, 'lbrynet.sqlite'))
    cur = db.cursor()
    files = cur.execute("select stream_hash, file_name, download_directory from file").fetchall()
    update = {}
    for stream_hash, file_name, download_directory in files:
        try:
            binascii.unhexlify(file_name)
        except binascii.Error:
            try:
                binascii.unhexlify(download_directory)
            except binascii.Error:
                update[stream_hash] = (
                    binascii.hexlify(file_name.encode()).decode(), binascii.hexlify(download_directory.encode()).decode()
                )
    if update:
        print(f"repair {len(update)} streams")
        for stream_hash, (file_name, download_directory) in update.items():
            cur.execute('update file set file_name=?, download_directory=? where stream_hash=?',
                        (file_name, download_directory, stream_hash))
    db.commit()
    db.close()


if __name__ == "__main__":
    main()
