import sqlite3
import logging
import os

from lbrynet.core.Error import InvalidStreamDescriptorError
from lbrynet.core.StreamDescriptor import EncryptedFileStreamType, format_sd_info, format_blobs, validate_descriptor
from lbrynet.cryptstream.CryptBlob import CryptBlobInfo

log = logging.getLogger(__name__)


def do_migration(db_dir):
    db_path = os.path.join(db_dir, "lbrynet.sqlite")
    blob_dir = os.path.join(db_dir, "blobfiles")
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()

    query = "select stream_name, stream_key, suggested_filename, sd_hash, stream_hash from stream"
    streams = cursor.execute(query).fetchall()

    blobs = cursor.execute("select s.stream_hash, s.position, s.iv, b.blob_hash, b.blob_length from stream_blob s "
                           "left outer join blob b ON b.blob_hash=s.blob_hash order by s.position").fetchall()
    blobs_by_stream = {}
    for stream_hash, position, iv, blob_hash, blob_length in blobs:
        blobs_by_stream.setdefault(stream_hash, []).append(CryptBlobInfo(blob_hash, position, blob_length or 0, iv))

    for stream_name, stream_key, suggested_filename, sd_hash, stream_hash in streams:
        sd_info = format_sd_info(
            EncryptedFileStreamType, stream_name, stream_key,
            suggested_filename, stream_hash, format_blobs(blobs_by_stream[stream_hash])
        )
        try:
            validate_descriptor(sd_info)
        except InvalidStreamDescriptorError as err:
            log.warning("Stream for descriptor %s is invalid (%s), cleaning it up",
                        sd_hash, err.message)
            blob_hashes = [blob.blob_hash for blob in blobs_by_stream[stream_hash]]
            delete_stream(cursor, stream_hash, sd_hash, blob_hashes, blob_dir)

    connection.commit()
    connection.close()


def delete_stream(transaction, stream_hash, sd_hash, blob_hashes, blob_dir):
    transaction.execute("delete from content_claim where stream_hash=? ", (stream_hash,))
    transaction.execute("delete from file where stream_hash=? ", (stream_hash, ))
    transaction.execute("delete from stream_blob where stream_hash=?", (stream_hash, ))
    transaction.execute("delete from stream where stream_hash=? ", (stream_hash, ))
    transaction.execute("delete from blob where blob_hash=?", (sd_hash, ))
    for blob_hash in blob_hashes:
        transaction.execute("delete from blob where blob_hash=?", (blob_hash, ))
        file_path = os.path.join(blob_dir, blob_hash)
        if os.path.isfile(file_path):
            os.unlink(file_path)
