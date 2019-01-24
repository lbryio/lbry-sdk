import platform
import os
import logging.handlers

from lbrynet.schema import __version__ as schema_version
from lbrynet import build_type, __version__ as lbrynet_version

log = logging.getLogger(__name__)


def get_platform() -> dict:
    p = {
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "os_release": platform.release(),
        "os_system": platform.system(),
        "lbrynet_version": lbrynet_version,
        "lbryschema_version": schema_version,
        "build": build_type.BUILD,  # CI server sets this during build step
    }
    if p["os_system"] == "Linux":
        import distro
        p["distro"] = distro.info()
        p["desktop"] = os.environ.get('XDG_CURRENT_DESKTOP', 'Unknown')

    return p
