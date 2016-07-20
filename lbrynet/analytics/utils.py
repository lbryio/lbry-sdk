import datetime

from lbrynet.core.utils import *


def now():
    """Return utc now in isoformat with timezone"""
    return datetime.datetime.utcnow().isoformat() + 'Z'
