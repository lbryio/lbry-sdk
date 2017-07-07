import platform
import json
import subprocess
import os
import sys

from urllib2 import urlopen
from lbryschema import __version__ as lbryschema_version
from lbryum import __version__ as LBRYUM_VERSION
from lbrynet import build_type, __version__ as lbrynet_version
from lbrynet.conf import ROOT_DIR


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
            sys.stderr.write("failed to get version from git\n")
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

    if get_ip:
        try:
            p['ip'] = json.load(urlopen('http://jsonip.com'))['ip']
        except:
            p['ip'] = "Could not determine IP"

    return p
