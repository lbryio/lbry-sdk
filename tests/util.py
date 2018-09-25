import datetime
import time
import os
import tempfile
import shutil
import mock
from binascii import hexlify


DEFAULT_TIMESTAMP = datetime.datetime(2016, 1, 1)
DEFAULT_ISO_TIME = time.mktime(DEFAULT_TIMESTAMP.timetuple())


def mk_db_and_blob_dir():
    db_dir = tempfile.mkdtemp()
    blob_dir = tempfile.mkdtemp()
    return db_dir, blob_dir


def rm_db_and_blob_dir(db_dir, blob_dir):
    shutil.rmtree(db_dir, ignore_errors=True)
    shutil.rmtree(blob_dir, ignore_errors=True)


def random_lbry_hash():
    return hexlify(os.urandom(48)).decode()


def resetTime(test_case, timestamp=DEFAULT_TIMESTAMP):
    iso_time = time.mktime(timestamp.timetuple())
    patcher = mock.patch('time.time')
    patcher.start().return_value = iso_time
    test_case.addCleanup(patcher.stop)

    patcher = mock.patch('lbrynet.core.utils.now')
    patcher.start().return_value = timestamp
    test_case.addCleanup(patcher.stop)

    patcher = mock.patch('lbrynet.core.utils.utcnow')
    patcher.start().return_value = timestamp
    test_case.addCleanup(patcher.stop)

def is_android():
    return 'ANDROID_ARGUMENT' in os.environ # detect Android using the Kivy way
