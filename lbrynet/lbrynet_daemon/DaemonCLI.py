import sys
import argparse
import json
from lbrynet import conf
import os
from lbrynet.lbrynet_daemon.auth.client import LBRYAPIClient
from jsonrpc.common import RPCError


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
        if '=' not in i:
            print 'WARNING: Argument "' + i + '" is missing a parameter name. Please use name=value'
            continue
        eq_pos = i.index('=')
        k, v = i[:eq_pos], i[eq_pos + 1:]
        params_for_return[k] = guess_type(v)
    return params_for_return


def main():
    conf.initialize_settings()
    api = LBRYAPIClient.config()

    try:
        status = api.daemon_status()
        assert status.get('code', False) == "started"
    except Exception:
        try:
            conf.settings.update({'use_auth_http': not conf.settings.use_auth_http})
            api = LBRYAPIClient.config()
            status = api.daemon_status()
            assert status.get('code', False) == "started"
        except Exception:
            print "lbrynet-daemon isn't running"
            sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument('method', nargs=1)
    parser.add_argument('params', nargs=argparse.REMAINDER, default=None)
    args = parser.parse_args()

    method = args.method[0]
    params = {}

    if len(args.params) > 1:
        params = get_params_from_kwargs(args.params)
    elif len(args.params) == 1:
        try:
            params = json.loads(args.params[0])
        except ValueError:
            params = get_params_from_kwargs(args.params)

    if method in ['--help', '-h', 'help']:
        helpmsg = api.help(params).strip()
        if params is not None and 'function' in params:
            print "\n" + params['function'] + ": " + helpmsg + "\n"
        else:
            print "Usage: lbrynet-cli method [params]\n" \
                  + "Examples: \n" \
                  + "  lbrynet-cli get_balance\n" \
                  + "  lbrynet-cli resolve_name name=what\n" \
                  + "  lbrynet-cli help function=resolve_name\n" \
                  + "\nAvailable functions:\n" \
                  + helpmsg + "\n"

    elif method not in api.commands():
        print "Error: function \"" + method + "\" does not exist.\n" + \
              "See \"" + os.path.basename(sys.argv[0]) + " help\""
    else:
        try:
            result = api.call(method, params)
            print json.dumps(result, sort_keys=True)
        except RPCError as err:
            # TODO: The api should return proper error codes
            # and messages so that they can be passed along to the user
            # instead of this generic message.
            # https://app.asana.com/0/158602294500137/200173944358192
            print "Something went wrong, here's the usage for %s:" % method
            print api.help({'function': method})
            print "Here's the traceback for the error you encountered:"
            print err.msg
        except KeyError as err:
            print "Something went wrong, here's the usage for %s:" % method
            print api.help({'function': method})
            if hasattr(err, 'msg'):
                print "Here's the traceback for the error you encountered:"
                print err.msg


if __name__ == '__main__':
    main()
