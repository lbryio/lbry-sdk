import logging
import random
from txjsonrpc.web.jsonrpc import Proxy
from lbrynet.conf import settings

log = logging.getLogger(__name__)


class LighthouseClient(object):
    def __init__(self, servers=None):
        self.servers = servers or settings.search_servers

    def _get_random_server(self):
        return Proxy(random.choice(self.servers))

    def _run_query(self, func, arg):
        return self._get_random_server().callRemote(func, arg)

    def search(self, search):
        return self._run_query('search', search)

    def announce_sd(self, sd_hash):
        log.info("Announce sd to lighthouse")
        return self._run_query('announce_sd', sd_hash)

    def check_available(self, sd_hash):
        return self._run_query('check_available', sd_hash)
