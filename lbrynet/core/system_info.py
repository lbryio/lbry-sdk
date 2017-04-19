import platform
import json

from urllib2 import urlopen

from lbrynet import __version__ as lbrynet_version
from lbrynet import build_type
from lbryum.version import LBRYUM_VERSION as lbryum_version
from lbryschema import __version__ as lbryschema_version


def get_platform(get_ip=True):
    p = {
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "os_release": platform.release(),
        "os_system": platform.system(),
        "lbrynet_version": lbrynet_version,
        "lbryum_version": lbryum_version,
        "lbryschema_version": lbryschema_version,
        "build": build_type.BUILD,  # CI server sets this during build step
    }

    if get_ip:
        try:
            p['ip'] = json.load(urlopen('http://jsonip.com'))['ip']
        except:
            p['ip'] = "Could not determine IP"

    return p
