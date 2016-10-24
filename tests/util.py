import datetime
import time

import mock


DEFAULT_TIMESTAMP = datetime.datetime(2016, 1, 1)
DEFAULT_ISO_TIME = time.mktime(DEFAULT_TIMESTAMP.timetuple())


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
