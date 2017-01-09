import sys
import argparse
import json
from lbrynet import conf
from lbrynet.lbrynet_daemon.auth.client import LBRYAPIClient
from jsonrpc.common import RPCError
from urllib2 import URLError



help_msg = "Usage: lbrynet-cli method kwargs\n" \
             + "Examples: " \
             + "lbrynet-cli resolve_name name=what\n" \
             + "lbrynet-cli get_balance\n" \
             + "lbrynet-cli help function=resolve_name\n" \
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
    conf.initialize_settings()
    api = LBRYAPIClient.config()

    try:
        status = api.daemon_status()
    except URLError:
        print "Could not connect to lbrynet-daemon. Are you sure it's running?"
        sys.exit(1)

    if status.get('code', False) != "started":
        print "Daemon is in the process of starting. Please try again in a bit."
        message = status.get('message', False)
        if message:
            print "  Status: " + message
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument('method', nargs=1)
    parser.add_argument('params', nargs=argparse.REMAINDER, default=None)
    args = parser.parse_args()

    meth = args.method[0]
    params = {}

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
                result = LBRYAPIClient.config(service=meth, params=params)
            else:
                result = LBRYAPIClient.config(service=meth, params=params)
            print json.dumps(result, sort_keys=True)
        except RPCError as err:
            # TODO: The api should return proper error codes
            # and messages so that they can be passed along to the user
            # instead of this generic message.
            # https://app.asana.com/0/158602294500137/200173944358192
            print "Something went wrong, here's the usage for %s:" % meth
            print api.help({'function': meth})
            print "Here's the traceback for the error you encountered:"
            print err.msg

    else:
        print "Unknown function"
        print msg


if __name__ == '__main__':
    main()
