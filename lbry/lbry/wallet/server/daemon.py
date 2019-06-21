from functools import wraps

from torba.rpc.jsonrpc import RPCError
from torba.server.daemon import Daemon, DaemonError


def handles_errors(decorated_function):
    @wraps(decorated_function)
    async def wrapper(*args, **kwargs):
        try:
            return await decorated_function(*args, **kwargs)
        except DaemonError as daemon_error:
            raise RPCError(1, daemon_error.args[0])
    return wrapper


class LBCDaemon(Daemon):
    @handles_errors
    async def getrawtransaction(self, hex_hash, verbose=False):
        return await super().getrawtransaction(hex_hash=hex_hash, verbose=verbose)

    @handles_errors
    async def getclaimbyid(self, claim_id):
        '''Given a claim id, retrieves claim information.'''
        return await self._send_single('getclaimbyid', (claim_id,))

    @handles_errors
    async def getclaimsbyids(self, claim_ids):
        '''Given a list of claim ids, batches calls to retrieve claim information.'''
        return await self._send_vector('getclaimbyid', ((claim_id,) for claim_id in claim_ids))

    @handles_errors
    async def getclaimsforname(self, name):
        '''Given a name, retrieves all claims matching that name.'''
        return await self._send_single('getclaimsforname', (name,))

    @handles_errors
    async def getclaimsfortx(self, txid):
        '''Given a txid, returns the claims it make.'''
        return await self._send_single('getclaimsfortx', (txid,)) or []

    @handles_errors
    async def getnameproof(self, name, block_hash=None):
        '''Given a name and optional block_hash, returns a name proof and winner, if any.'''
        return await self._send_single('getnameproof', (name, block_hash,) if block_hash else (name,))

    @handles_errors
    async def getvalueforname(self, name):
        '''Given a name, returns the winning claim value.'''
        return await self._send_single('getvalueforname', (name,))

    @handles_errors
    async def claimname(self, name, hexvalue, amount):
        '''Claim a name, used for functional tests only.'''
        return await self._send_single('claimname', (name, hexvalue, float(amount)))
