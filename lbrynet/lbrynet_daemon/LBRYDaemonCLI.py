import sys
import json
import argparse

from lbrynet.lbrynet_daemon.auth.client import LBRYAPIClient

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


def get_params_from_kwargs(params):
    params_for_return = {}
    for i in params:
        eq_pos = i.index('=')
        k, v = i[:eq_pos], i[eq_pos+1:]
        params_for_return[k] = guess_type(v)
    return params_for_return


def main():
    api = LBRYAPIClient()

    try:
        s = api.is_running()
    except:
        print "lbrynet-daemon isn't running"
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument('method', nargs=1)
    parser.add_argument('params', nargs=argparse.REMAINDER, default=None)
    args = parser.parse_args()

    meth = args.method[0]
    params = {}

    if args.params:
        if len(args.params) > 1:
            params = get_params_from_kwargs(args.params)
        elif len(args.params) == 1:
            try:
                params = json.loads(args.params[0])
            except ValueError:
                params = get_params_from_kwargs(args.params)

    msg = help_msg
    for f in api.help():
        msg += f + "\n"

    if meth in ['--help', '-h', 'help']:
        print msg
        sys.exit(1)

    if meth in api.help():
        try:
            if params:
                r = LBRYAPIClient(service=meth)(params)
            else:
                r = LBRYAPIClient(service=meth)()
            print json.dumps(r, sort_keys=True)
        except:
            print "Something went wrong, here's the usage for %s:" % meth
            print api.help({'function': meth})
    else:
        print "Unknown function"
        print msg


if __name__ == '__main__':
    main()
