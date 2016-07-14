import sys
import json

from lbrynet.conf import API_CONNECTION_STRING, LOG_FILE_NAME
from jsonrpc.proxy import JSONRPCProxy

help_msg = "Useage: lbrynet-cli method json-args\n" \
             + "Examples: " \
             + "lbrynet-cli resolve_name '{\"name\": \"what\"}'\n" \
             + "lbrynet-cli get_balance\n" \
             + "lbrynet-cli help '{\"function\": \"resolve_name\"}'\n" \
             + "\n******lbrynet-cli functions******\n"


def main():
    api = JSONRPCProxy.from_url(API_CONNECTION_STRING)

    try:
        s = api.is_running()
    except:
        print "lbrynet-daemon isn't running"
        sys.exit(1)

    args = sys.argv[1:]
    meth = args[0]

    msg = help_msg
    for f in api.help():
        msg += f + "\n"

    if meth in ['--help', '-h', 'help']:
        print msg
        sys.exit(1)

    if len(args) > 1:
        if isinstance(args[1], dict):
            params = args[1]
        elif isinstance(args[1], str) or isinstance(args[1], unicode):
            params = json.loads(args[1])
    else:
        params = None

    if meth in api.help():
        try:
            if params:
                r = api.call(meth, params)
            else:
                r = api.call(meth)
            print r
        except:
            print "Something went wrong, here's the usage for %s:" % meth
            print api.help({'function': meth})
    else:
        print "Unknown function"
        print msg


if __name__ == '__main__':
    main()
