import os
import re
import json
import inspect
import tempfile
from docopt import docopt
from lbrynet.extras.cli import set_kwargs, get_argument_parser
from lbrynet.extras.daemon.Daemon import Daemon, jsonrpc_dumps_pretty
from lbrynet.testcase import CommandTestCase


class ExampleRecorder:
    def __init__(self, test):
        self.test = test
        self.examples = {}

    async def __call__(self, title, *command):
        parser = get_argument_parser()
        args, command_args = parser.parse_known_args(command)

        api_method_name = args.api_method_name
        parsed = docopt(args.doc, command_args)
        kwargs = set_kwargs(parsed)
        params = json.dumps({"method": api_method_name, "params": kwargs})

        method = getattr(self.test.daemon, f'jsonrpc_{api_method_name}')
        output = jsonrpc_dumps_pretty(await method(**kwargs), ledger=self.test.daemon.ledger)
        self.examples.setdefault(api_method_name, []).append({
            'title': title,
            'curl': f"curl -d'{params}' http://localhost:5279/",
            'lbrynet': 'lbrynet ' + ' '.join(command),
            'python': f'requests.post("http://localhost:5279", json={params}).json()',
            'output': output.strip()
        })
        return json.loads(output)['result']


class Examples(CommandTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.recorder = ExampleRecorder(self)

    async def play(self):
        r = self.recorder

        await r(
            'List your accounts.',
            'account', 'list'
        )

        with tempfile.NamedTemporaryFile() as file:
            file.write(b'hello world')
            file.flush()
            claim = await r(
                'Publish a file.',
                'publish', 'aname', '1.0', f'--file_path={file.name}'
            )
            self.assertTrue(claim['success'])
            await self.on_transaction_dict(claim['tx'])
            await self.generate(1)
            await self.on_transaction_dict(claim['tx'])

        await r(
            'List your claims.',
            'claim', 'list_mine'
        )

        await r(
            'Abandon a published file.',
            'claim', 'abandon', claim['claim_id']
        )


def get_examples():
    player = Examples('play')
    player.run()
    return player.recorder.examples


SECTIONS = re.compile("(.*?)Usage:(.*?)Options:(.*?)Returns:(.*)", re.DOTALL)
REQUIRED_OPTIONS = re.compile("\(<(.*?)>.*?\)")
ARGUMENT_NAME = re.compile("--([^=]+)")
ARGUMENT_TYPE = re.compile("\s*\((.*?)\)(.*)")


def get_api(name, examples):
    obj = Daemon.callable_methods[name]
    docstr = inspect.getdoc(obj).strip()

    try:
        description, usage, options, returns = SECTIONS.search(docstr).groups()
    except:
        raise ValueError(f"Doc string format error for {obj.__name__}.")

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
        'name': name,
        'description': description.strip(),
        'arguments': arguments,
        'returns': returns.strip(),
        'examples': examples
    }


def write_api(f):
    examples = get_examples()
    apis = []
    for method_name in sorted(Daemon.callable_methods.keys()):
        apis.append(get_api(
            method_name,
            examples.get(method_name, [])
        ))
    json.dump(apis, f, indent=4)


if __name__ == '__main__':
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html_file = os.path.join(parent, 'docs', 'api.json')
    with open(html_file, 'w+') as f:
        write_api(f)
