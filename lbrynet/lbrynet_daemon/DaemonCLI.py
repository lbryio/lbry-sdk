import sys
import argparse
import json
from lbrynet import conf
import os
from lbrynet.lbrynet_daemon.auth.client import LBRYAPIClient
from lbrynet.lbrynet_daemon.Daemon import LOADING_WALLET_CODE
from jsonrpc.common import RPCError
from urllib2 import URLError


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
        params_for_return[i[:eq_pos]] = guess_type(i[eq_pos + 1:])
    return params_for_return


def print_help():
    print "\n".join([
        "NAME",
        "   lbrynet-cli - LBRY command line client.",
        "",
        "USAGE",
        "   lbrynet-cli <command> [<args>]",
        "",
        "EXAMPLES",
        "   lbrynet-cli commands                    # list available commands",
        "   lbrynet-cli status                      # get daemon status",
        "   lbrynet-cli resolve_name name=what      # resolve a name",
        "   lbrynet-cli help function=resolve_name  # get help about a method",
    ])


def wrap_list_to_term_width(l, width=None, separator=', ', prefix=''):
    if width is None:
        try:
            _, width = os.popen('stty size', 'r').read().split()
            width = int(width)
        except:
            pass
        if not width:
            width = 80

    lines = []
    curr_line = prefix
    for item in l:
        new_line = curr_line + item + separator
        if len(new_line) > width:
            lines.append(curr_line)
            curr_line = prefix + item + separator
        else:
            curr_line = new_line

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('params', nargs=argparse.ZERO_OR_MORE, default=None)
    args = parser.parse_args()

    if len(args.params) < 1:
        print_help()
        sys.exit(1)

    method = args.params[0]
    params = args.params[1:]

    if len(params) > 1:
        params = get_params_from_kwargs(params)
    elif len(params) == 1:
        try:
            params = json.loads(params[0])
        except ValueError:
            params = get_params_from_kwargs(params)
    else:
        params = {}

    conf.initialize_settings()
    api = LBRYAPIClient.get_client()

    # TODO: check if port is bound

    try:
        status = api.status()
    except URLError:
        print "Could not connect to lbrynet-daemon. Are you sure it's running?"
        sys.exit(1)

    if status['startup_status']['code'] != "started":
        print "Daemon is in the process of starting. Please try again in a bit."
        message = status['startup_status']['message']
        if message:
            if status['startup_status']['code'] == LOADING_WALLET_CODE \
                    and status['blocks_behind'] > 0:
                message += '. Blocks left: ' + str(status['blocks_behind'])
            print "  Status: " + message
        sys.exit(1)

    if method in ['--help', '-h', 'help']:
        if len(params) == 0:
            print_help()
            print "\nCOMMANDS\n" + wrap_list_to_term_width(api.commands(), prefix='   ')
        else:
            print api.help(params).strip()

    elif method not in api.commands():
        print (
            "Function '" + method + "' is not a valid function.\n"
            "See '" + os.path.basename(sys.argv[0]) + " help'"
        )

    else:
        try:
            result = api.call(method, params)
            print json.dumps(result, sort_keys=True, indent=2)
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
