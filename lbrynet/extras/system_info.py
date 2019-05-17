import platform
import os
import logging.handlers

from lbrynet import build_type, __version__ as lbrynet_version

log = logging.getLogger(__name__)


def get_platform() -> dict:
    os_system = platform.system()
    if os.environ and 'ANDROID_ARGUMENT' in os.environ:
        os_system = 'android'
    p = {
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "os_release": platform.release(),
        "os_system": os_system,
        "lbrynet_version": lbrynet_version,
        "build": build_type.BUILD,  # CI server sets this during build step
    }
    if p["os_system"] == "Linux":
        import distro
        p["distro"] = distro.info()
        p["desktop"] = os.environ.get('XDG_CURRENT_DESKTOP', 'Unknown')

    return p
