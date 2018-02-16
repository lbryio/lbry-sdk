import platform
import json
import subprocess
import os
import logging

from urllib2 import urlopen, URLError
from lbryschema import __version__ as lbryschema_version
from lbryum import __version__ as LBRYUM_VERSION
from lbrynet import build_type, __version__ as lbrynet_version
from lbrynet import conf
from lbrynet.conf import ROOT_DIR

log = logging.getLogger(__name__)

def get_lbrynet_version():
    if build_type.BUILD == "dev":
        try:
            with open(os.devnull, 'w') as devnull:
                git_dir = ROOT_DIR + '/.git'
                return subprocess.check_output(
                    ['git', '--git-dir='+git_dir, 'describe', '--dirty', '--always'],
                    stderr=devnull
                ).strip().lstrip('v')
        except (subprocess.CalledProcessError, OSError):
            print "failed to get version from git"
    return lbrynet_version


def get_platform(get_ip=True):
    p = {
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "os_release": platform.release(),
        "os_system": platform.system(),
        "lbrynet_version": get_lbrynet_version(),
        "lbryum_version": LBRYUM_VERSION,
        "lbryschema_version": lbryschema_version,
        "build": build_type.BUILD,  # CI server sets this during build step
    }

    # TODO: remove this from get_platform and add a get_external_ip function using txrequests
    if get_ip:
        if conf.settings.is_default('external_ip'):
            try:
                response = json.loads(urlopen("https://api.lbry.io/ip").read())
                if not response['success']:
                    raise URLError("failed to get external ip")
                p['ip'] = response['data']['ip']
            except (URLError, AssertionError):
                p['ip'] = "Could not determine IP"
        else:
            p['ip'] = conf.settings['external_ip']
            log.info('Using configured external IP: %s' % p['ip'])

    return p
