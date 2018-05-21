import datetime
import time
import binascii
import os
import tempfile
import shutil
import mock
import logging

from lbrynet.dht.encoding import Bencode
from lbrynet.dht.error import DecodeError
from lbrynet.dht.msgformat import DefaultFormat
from lbrynet.dht.msgtypes import ResponseMessage, RequestMessage, ErrorMessage

_encode = Bencode()
_datagram_formatter = DefaultFormat()
DEFAULT_TIMESTAMP = datetime.datetime(2016, 1, 1)
DEFAULT_ISO_TIME = time.mktime(DEFAULT_TIMESTAMP.timetuple())

log = logging.getLogger("lbrynet.tests.util")

def mk_db_and_blob_dir():
    db_dir = tempfile.mkdtemp()
    blob_dir = tempfile.mkdtemp()
    return db_dir, blob_dir


def rm_db_and_blob_dir(db_dir, blob_dir):
    shutil.rmtree(db_dir, ignore_errors=True)
    shutil.rmtree(blob_dir, ignore_errors=True)


def random_lbry_hash():
    return binascii.b2a_hex(os.urandom(48))


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


def debug_kademlia_packet(data, source, destination, node):
    if log.level != logging.DEBUG:
        return
    try:
        packet = _datagram_formatter.fromPrimitive(_encode.decode(data))
        if isinstance(packet, RequestMessage):
            log.debug("request %s --> %s %s (node time %s)", source[0], destination[0], packet.request,
                      node.clock.seconds())
        elif isinstance(packet, ResponseMessage):
            if isinstance(packet.response, (str, unicode)):
                log.debug("response %s <-- %s %s (node time %s)", destination[0], source[0], packet.response,
                          node.clock.seconds())
            else:
                log.debug("response %s <-- %s %i contacts (node time %s)", destination[0], source[0],
                          len(packet.response), node.clock.seconds())
        elif isinstance(packet, ErrorMessage):
            log.error("error %s <-- %s %s (node time %s)", destination[0], source[0], packet.exceptionType,
                      node.clock.seconds())
    except DecodeError:
        log.exception("decode error %s --> %s (node time %s)", source[0], destination[0], node.clock.seconds())
