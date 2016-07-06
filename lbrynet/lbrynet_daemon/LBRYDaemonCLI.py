import sys
import json

from lbrynet.conf import API_CONNECTION_STRING, LOG_FILE_NAME
from jsonrpc.proxy import JSONRPCProxy


def main():
    api = JSONRPCProxy.from_url(API_CONNECTION_STRING)

    try:
        s = api.is_running()
    except:
        print "lbrynet-daemon isn't running"
        sys.exit(1)

    args = sys.argv[1:]
    meth = args[0]
    if len(args) > 1:
        if isinstance(args[1], dict):
            params = args[1]
        elif isinstance(args[1], str) or isinstance(args[1], unicode):
            params = json.loads(args[1])
    else:
        params = None

    if meth in api.help():
        if params:
            r = api.call(meth, params)
        else:
            r = api.call(meth)
        print r
    else:
        print "Unrecognized function"


if __name__ == '__main__':
    main()