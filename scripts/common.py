import logging

from twisted.internet import defer


log = logging.getLogger(__name__)


@defer.inlineCallbacks
def getNames(wallet, names=None):
    if names:
        defer.returnValue(names)
    nametrie = yield wallet.get_nametrie()
    defer.returnValue(list(getNameClaims(nametrie)))


def getNameClaims(trie):
    for x in trie:
        if 'txid' in x:
            try:
                yield str(x['name'])
            except UnicodeError:
                log.warning('Skippin name %s as it is not ascii', x['name'])
