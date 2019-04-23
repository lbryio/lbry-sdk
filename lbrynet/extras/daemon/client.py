from lbrynet.conf import Config
from lbrynet.extras.cli import execute_command


def daemon_rpc(conf: Config, method: str, **kwargs):
    return execute_command(conf, method, kwargs, callback=lambda data: data)
