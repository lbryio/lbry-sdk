from twisted.internet import defer


class migrator(object):
    """
    Re-resolve lbry names to write missing data to blockchain.db and to cache the nametrie
    """

    def __init__(self, api):
        self._api = api

    def start(self):
        def _resolve_claims(claimtrie):
            claims = [i for i in claimtrie if 'txid' in i.keys()]
            r = defer.DeferredList([self._api._resolve_name(claim['name'], force_refresh=True) for claim in claims], consumeErrors=True)
            return r

        def _restart_lbry_files():
            def _restart_lbry_file(lbry_file):
                return lbry_file.restore()

            r = defer.DeferredList([_restart_lbry_file(lbry_file) for lbry_file in self._api.lbry_file_manager.lbry_files if not lbry_file.txid], consumeErrors=True)
            return r

        d = self._api.session.wallet.get_nametrie()
        d.addCallback(_resolve_claims)
        d.addCallback(lambda _: _restart_lbry_files())


def run(api):
    refresher = migrator(api)
    refresher.start()
