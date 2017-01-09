import argparse
import json
import os
import sys

from lbrynet import conf
from lbrynet.lbrynet_daemon.auth.client import LBRYAPIClient
from lbrynet.lbrynet_daemon.Daemon import LOADING_WALLET_CODE
from jsonrpc.common import RPCError
from urllib2 import URLError


def main():
    parser = argparse.ArgumentParser(add_help=False)
    _, arguments = parser.parse_known_args()

    if len(arguments) < 1:
        print_help()
        return 1

    method = arguments[0]
    try:
        params = parse_params(arguments[1:])
    except InvalidParameters as e:
        print_error(e.message)
        return 1

    conf.initialize_settings()
    api = LBRYAPIClient.get_client()

    # TODO: check if port is bound. Error if its not

    try:
        status = api.status()
    except URLError:
        print_error("Could not connect to daemon. Are you sure it's running?",
                    suggest_help=False)
        return 1

    if status['startup_status']['code'] != "started":
        print "Daemon is in the process of starting. Please try again in a bit."
        message = status['startup_status']['message']
        if message:
            if (
                status['startup_status']['code'] == LOADING_WALLET_CODE
                and status['blocks_behind'] > 0
            ):
                message += '. Blocks left: ' + str(status['blocks_behind'])
            print "  Status: " + message
        return 1

    if method in ['--help', '-h', 'help']:
        if len(params) == 0:
            print_help()
            print "\nCOMMANDS\n" + wrap_list_to_term_width(api.commands(), prefix='   ')
        else:
            print api.help(params).strip()

    elif method not in api.commands():
        print_error("Function '" + method + "' is not a valid function.")

    else:
        try:
            result = api.call(method, params)
            if isinstance(result, basestring):
                # printing the undumped string is prettier
                print result
            else:
                print json.dumps(result, sort_keys=True, indent=2, separators=(',', ': '))
        except RPCError as err:
            handle_error(err, api, method)
        except KeyError as err:
            handle_error(err, api, method)


def handle_error(err, api, method):
    # TODO: The api should return proper error codes
    # and messages so that they can be passed along to the user
    # instead of this generic message.
    # https://app.asana.com/0/158602294500137/200173944358192
    print "Something went wrong, here's the usage for %s:" % method
    print api.help({'function': method})
    if hasattr(err, 'msg'):
        print "Here's the traceback for the error you encountered:"
        print err.msg


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


def parse_params(params):
    if len(params) > 1:
        return get_params_from_kwargs(params)
    elif len(params) == 1:
        try:
            return json.loads(params[0])
        except ValueError:
            return get_params_from_kwargs(params)
    else:
        return {}


class InvalidParameters(Exception):
    pass


def get_params_from_kwargs(params):
    params_for_return = {}
    for i in params:
        try:
            eq_pos = i.index('=')
        except ValueError:
            raise InvalidParameters('{} is not in <key>=<value> format'.format(i))
        k, v = i[:eq_pos], i[eq_pos + 1:]
        params_for_return[k] = guess_type(v)
    return params_for_return


def print_help_suggestion():
    print "See `{} help` for more information.".format(os.path.basename(sys.argv[0]))


def print_error(message, suggest_help=True):
    print "ERROR: " + message
    if suggest_help:
        print_help_suggestion()


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
    curr_line = ''
    for item in l:
        new_line = curr_line + item + separator
        if len(new_line) + len(prefix) > width:
            lines.append(curr_line)
            curr_line = item + separator
        else:
            curr_line = new_line
    lines.append(curr_line)

    ret = prefix + ("\n" + prefix).join(lines)
    if ret.endswith(separator):
        ret = ret[:-len(separator)]
    return ret


if __name__ == '__main__':
    sys.exit(main())
