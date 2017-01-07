import argparse
import json
import os
import sys

from jsonrpc.common import RPCError

from lbrynet import conf
from lbrynet.lbrynet_daemon.auth.client import LBRYAPIClient


HELP_MSG = "Usage: lbrynet-cli method kwargs\n" \
             + "Examples: \n" \
             + "lbrynet-cli resolve_name name=what\n" \
             + "lbrynet-cli get_balance\n" \
             + "lbrynet-cli help function=resolve_name\n" \



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
            return 1

    epilog = "use `{} help` for more information".format(os.path.basename(sys.argv[0]))

    parser = argparse.ArgumentParser(epilog=epilog)
    parser.add_argument('method', nargs=1)
    parser.add_argument('params', nargs=argparse.REMAINDER, default=None)
    args = parser.parse_args()

    meth = args.method[0]

    if meth == 'help' and not args.params:
        print help_msg_with_function_list(api)
        return

    try:
        params = parse_params(args.params)
    except InvalidParams:
        print_usage(api, meth)
        print HELP_MSG
        return

    if meth in api.help():
        try:
            call_method(meth, params)
            return
        except RPCError as err:
            handle_error(err, api, meth)
            return 1
    else:
        print "Unknown function"
        print help_msg_with_function_list(api)
        return 1


def call_method(meth, params):
    if params:
        json_result = LBRYAPIClient.config(service=meth, params=params)
    else:
        json_result = LBRYAPIClient.config(service=meth, params=params)
    if isinstance(json_result, basestring):
        # printing the undumped string is prettier
        print json_result
    else:
        print json.dumps(json_result, sort_keys=True,
                         indent=2, separators=(',', ': '))


def handle_error(err, api, meth):
    # TODO: The api should return proper error codes
    # and messages so that they can be passed along to the user
    # instead of this generic message.
    # https://app.asana.com/0/158602294500137/200173944358192
    print_usage(api, meth)
    print
    print "Here's the traceback for the error you encountered:"
    print err.msg


def help_msg_with_function_list(api):
    msg = [HELP_MSG, "\n******lbrynet-cli functions******\n"]
    for f in api.help():
        msg.append(f)
    return '\n'.join(msg)


def parse_params(params):
    if len(params) > 1:
        return get_params_from_kwargs(params)

    elif len(params) == 1:
        try:
            return json.loads(params[0])
        except ValueError:
            return get_params_from_kwargs(params)


class InvalidParams(Exception):
    pass


def get_params_from_kwargs(params):
    params_for_return = {}
    for i in params:
        try:
            eq_pos = i.index('=')
        except ValueError:
            raise InvalidParams('{} is not in <key>=<value> format'.format(i))
        k, v = i[:eq_pos], i[eq_pos+1:]
        params_for_return[k] = guess_type(v)
    return params_for_return


def print_usage(api, meth):
    print "Something went wrong, here's the usage for %s:" % meth
    print api.help({'function': meth})


if __name__ == '__main__':
    sys.exit(main())
