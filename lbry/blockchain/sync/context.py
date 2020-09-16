from contextvars import ContextVar
from lbry.db import query_context

from lbry.blockchain.lbrycrd import Lbrycrd


_chain: ContextVar[Lbrycrd] = ContextVar('chain')


def get_or_initialize_lbrycrd(ctx=None) -> Lbrycrd:
    chain = _chain.get(None)
    if chain is not None:
        return chain
    chain = Lbrycrd((ctx or query_context.context()).ledger)
    chain.db.sync_open()
    _chain.set(chain)
    return chain


def uninitialize():
    chain = _chain.get(None)
    if chain is not None:
        chain.db.sync_close()
        chain.sync_run(chain.close_session())
        _chain.set(None)
