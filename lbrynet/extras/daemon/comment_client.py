import logging
import aiohttp

log = logging.getLogger(__name__)


def rpc_body(method: str, rpc_id: any, **params) -> dict:
    return {'jsonrpc': '2.0', 'id': rpc_id, 'method': method, 'params': {**params}}


async def jsonrpc_post(url: str, method: str, **params) -> any:
    clean = params.pop('clean', True)
    response = (await jsonrpc_batch(url, [rpc_body(method, 1, **params)]))[0]
    if clean:
        if 'error' in response:
            return response['error']
        return response['result']
    else:
        return response


async def jsonrpc_batch(url: str, calls: list, batch_size: int = 50, clean: bool = False) -> list:
    headers = {'Content-Type': 'application/json'}
    complete = []
    batch_size = max(batch_size, 50)
    for i in range(0, len(calls), batch_size):
        async with aiohttp.request('POST', url, headers=headers, json=calls[i:i+batch_size]) as response:
            complete += await response.json()
    if clean:
        complete = [body['result'] if 'result' in body else None for body in complete]
    return complete
