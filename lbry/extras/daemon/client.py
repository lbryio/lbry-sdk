from lbry.conf import Config
from lbry.extras.cli import execute_command


def daemon_rpc(conf: Config, method: str, **kwargs):
    return execute_command(conf, method, kwargs, callback=lambda data: data)
