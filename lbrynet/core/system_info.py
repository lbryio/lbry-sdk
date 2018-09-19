import platform
import json
import subprocess
import os

from six.moves.urllib import request
from six.moves.urllib.error import URLError
from lbryschema import __version__ as lbryschema_version
from lbrynet import build_type, __version__ as lbrynet_version
from lbrynet.conf import ROOT_DIR
import logging.handlers

log = logging.getLogger(__name__)


def get_lbrynet_version():
    if build_type.BUILD == "dev":
        try:
            with open(os.devnull, 'w') as devnull:
                git_dir = ROOT_DIR + '/.git'
                return subprocess.check_output(
                    ['git', '--git-dir='+git_dir, 'describe', '--dirty', '--always'],
                    stderr=devnull
                ).decode().strip().lstrip('v')
        except (subprocess.CalledProcessError, OSError):
            log.debug("failed to get version from git")
    return lbrynet_version


def get_platform(get_ip=True):
    p = {
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "os_release": platform.release(),
        "os_system": platform.system(),
        "lbrynet_version": get_lbrynet_version(),
        "lbryschema_version": lbryschema_version,
        "build": build_type.BUILD,  # CI server sets this during build step
    }
    if p["os_system"] == "Linux":
        try:
            import distro
            p["distro"] = distro.info()
            p["desktop"] = os.environ.get('XDG_CURRENT_DESKTOP', 'Unknown')
        except ModuleNotFoundError:
            pass

    # TODO: remove this from get_platform and add a get_external_ip function using treq
    if get_ip:
        try:
            response = json.loads(request.urlopen("https://api.lbry.io/ip").read())
            if not response['success']:
                raise URLError("failed to get external ip")
            p['ip'] = response['data']['ip']
        except (URLError, AssertionError):
            p['ip'] = "Could not determine IP"

    return p
