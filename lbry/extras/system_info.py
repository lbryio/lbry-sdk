import platform
import os
import logging.handlers

from lbry import build_info, __version__ as lbrynet_version

log = logging.getLogger(__name__)


def get_platform() -> dict:
    os_system = platform.system()
    if os.environ and 'ANDROID_ARGUMENT' in os.environ:
        os_system = 'android'
    d = {
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "os_release": platform.release(),
        "os_system": os_system,
        "lbrynet_version": lbrynet_version,
        "version": lbrynet_version,
        "build": build_info.BUILD,  # CI server sets this during build step
    }
    if d["os_system"] == "Linux":
        import distro  # pylint: disable=import-outside-toplevel
        d["distro"] = distro.info()
        d["desktop"] = os.environ.get('XDG_CURRENT_DESKTOP', 'Unknown')

    return d
