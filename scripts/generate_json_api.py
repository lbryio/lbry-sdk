import os
import re
import json
import inspect
from textwrap import dedent
from lbrynet.daemon.Daemon import Daemon


SECTIONS = re.compile("(.*?)Usage:(.*?)Options:(.*?)Returns:(.*)", re.DOTALL)
REQUIRED_OPTIONS = re.compile("\(<(.*?)>.*?\)")
ARGUMENT_NAME = re.compile("--([^=]+)")
ARGUMENT_TYPE = re.compile("\s*\((.*?)\)(.*)")


def get_api(obj):
    docstr = inspect.getdoc(obj).strip()

    try:
        description, usage, options, returns = SECTIONS.search(docstr).groups()
    except:
        raise ValueError("Doc string format error for {}.".format(obj.__name__))

    required = re.findall(REQUIRED_OPTIONS, usage)

    arguments = []
    for line in options.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('--'):
            arg, desc = line.split(':', 1)
            arg_name = ARGUMENT_NAME.search(arg).group(1)
            arg_type, arg_desc = ARGUMENT_TYPE.search(desc).groups()
            arguments.append({
                'name': arg_name.strip(),
                'type': arg_type.strip(),
                'description': [arg_desc.strip()],
                'is_required': arg_name in required
            })
        elif line == 'None':
            continue
        else:
            arguments[-1]['description'].append(line.strip())

    for arg in arguments:
        arg['description'] = ' '.join(arg['description'])

    return {
        'name': obj.__name__[len('jsonrpc_'):],
        'description': description.strip(),
        'arguments': arguments,
        'returns': returns.strip()
    }


def write_api(f):
    apis = []
    for method_name in sorted(Daemon.callable_methods.keys()):
        apis.append(get_api(Daemon.callable_methods[method_name]))
    json.dump(apis, f, indent=4)


if __name__ == '__main__':
    html_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'docs', 'api.json')
    with open(html_file, 'w+') as f:
        write_api(f)
