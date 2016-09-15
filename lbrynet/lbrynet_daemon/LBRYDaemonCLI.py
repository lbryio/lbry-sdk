import sys
import json
import argparse

from lbrynet.conf import API_CONNECTION_STRING
from jsonrpc.proxy import JSONRPCProxy

help_msg = "Usage: lbrynet-cli method json-args\n" \
             + "Examples: " \
             + "lbrynet-cli resolve_name '{\"name\": \"what\"}'\n" \
             + "lbrynet-cli get_balance\n" \
             + "lbrynet-cli help '{\"function\": \"resolve_name\"}'\n" \
             + "\n******lbrynet-cli functions******\n"


def guess_type(x):
    if '.' in x:
        try:
            return float(x)
        except ValueError:
            # not a float
            pass
    try:
        return int(x)
    except ValueError:
        return x

def main():
    api = JSONRPCProxy.from_url(API_CONNECTION_STRING)

    try:
        s = api.is_running()
    except:
        print "lbrynet-daemon isn't running"
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument('method', nargs=1, type=str)
    parser.add_argument('params', nargs="+")
    args = parser.parse_args()
    meth = args.method[0]
    params = {}
    if args.params:
        if len(args.params) != 1:
            for i in args.params:
                k, v = i.split('=')[0], i.split('=')[1:]
                if isinstance(v, list):
                    v = ''.join(v)
                params[k] = guess_type(v)
        else:
            try:
                params = json.loads(args.params[0])
            except ValueError:
                for i in args.params:
                    k, v = i.split('=')[0], i.split('=')[1:]
                    if isinstance(v, list):
                        v = ''.join(v)
                    params[k] = guess_type(v)

    msg = help_msg
    for f in api.help():
        msg += f + "\n"

    if meth in ['--help', '-h', 'help']:
        print msg
        sys.exit(1)

    if meth in api.help():
        try:
            if params:
                r = api.call(meth, params)
            else:
                r = api.call(meth)
            print json.dumps(r, sort_keys=True)
        except:
            print "Something went wrong, here's the usage for %s:" % meth
            print api.help({'function': meth})
    else:
        print "Unknown function"
        print msg


if __name__ == '__main__':
    main()
