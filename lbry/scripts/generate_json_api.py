import os
import re
import json
import inspect
import tempfile
import asyncio
import time
from docopt import docopt
from binascii import unhexlify
from textwrap import indent
from lbry.extras.cli import set_kwargs, get_argument_parser
from lbry.extras.daemon.Daemon import (
    Daemon, jsonrpc_dumps_pretty, encode_pagination_doc
)
from lbry.extras.daemon.json_response_encoder import (
    encode_tx_doc, encode_txo_doc, encode_account_doc, encode_file_doc
)
from lbry.testcase import CommandTestCase


RETURN_DOCS = {
    'Account': encode_account_doc(),
    'File': encode_file_doc(),
    'Transaction': encode_tx_doc(),
    'Output': encode_txo_doc(),
    'Address': 'an address in base58'
}


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
        for k, v in kwargs.items():
            if v and isinstance(v, str) and (v[0], v[-1]) == ('"', '"'):
                kwargs[k] = v[1:-1]
        params = json.dumps({"method": api_method_name, "params": kwargs})

        method = getattr(self.test.daemon, f'jsonrpc_{api_method_name}')
        result = method(**kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        output = jsonrpc_dumps_pretty(result, ledger=self.test.daemon.ledger)
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

        # general sdk

        await r(
            'Get status',
            'status'
        )
        await r(
            'Get version',
            'version'
        )
        await r(
            'Get settings',
            'settings', 'get'
        )

        # accounts

        await r(
            'List your accounts',
            'account', 'list'
        )

        account = await r(
            'Create an account',
            'account', 'create', '"generated account"'
        )

        await r(
            'Remove an account',
            'account', 'remove', account['id']
        )

        await r(
            'Add an account from seed',
            'account', 'add', '"new account"', f"--seed=\"{account['seed']}\""
        )

        await r(
            'Modify maximum number of times a change address can be reused',
            'account', 'set', account['id'], '--change_max_uses=10'
        )

        # addresses

        await r(
            'List addresses in default account',
            'address', 'list'
        )

        an_address = await r(
            'Get an unused address',
            'address', 'unused'
        )

        address_list_by_id = await r(
            'List addresses in specified account',
            'address', 'list', f"--account_id=\"{account['id']}\""
        )

        await r(
            'Check if address is mine',
            'address', 'is_mine', an_address
        )

        # sends/funds

        transfer = await r(
            'Transfer 2 LBC from default account to specific account',
            'account', 'fund', f"--to_account=\"{account['id']}\"", "--amount=2.0", "--broadcast"
        )

        await self.on_transaction_dict(transfer)
        await self.generate(1)
        await self.on_transaction_dict(transfer)

        await r(
            'Get default account balance',
            'account', 'balance'
        )

        txlist = await r(
            'List your transactions',
            'transaction', 'list'
        )

        await r(
            'Get balance for specific account by id',
            'account', 'balance', f"\"{account['id']}\""
        )

        spread_transaction = await r(
            'Spread LBC between multiple addresses',
            'account', 'fund', f"--to_account=\"{account['id']}\"", f"--from_account=\"{account['id']}\"", '--amount=1.5', '--outputs=2', '--broadcast'
        )

        await self.on_transaction_dict(spread_transaction)
        await self.generate(1)
        await self.on_transaction_dict(spread_transaction)

        await r(
            'Transfer all LBC to a specified account',
            'account', 'fund', f"--from_account=\"{account['id']}\"", "--everything", "--broadcast"
        )

        # channels

        channel = await r(
            'Create a channel claim without metadata',
            'channel', 'create', '@channel', '1.0'
        )
        channel_id = channel['outputs'][0]['claim_id']
        await self.on_transaction_dict(channel)
        await self.generate(1)
        await self.on_transaction_dict(channel)

        await r(
            'List your channel claims',
            'channel', 'list'
        )

        await r(
            'Paginate your channel claims',
            'channel', 'list', '--page=1', '--page_size=20'
        )

        channel = await r(
            'Update a channel claim',
            'channel', 'update', channel['outputs'][0]['claim_id'], '--title="New Channel"'
        )

        await self.on_transaction_dict(channel)
        await self.generate(1)
        await self.on_transaction_dict(channel)

        big_channel = await r(
            'Create a channel claim with all metadata',
            'channel', 'create', '@bigchannel', '1.0',
            '--title="Big Channel"', '--description="A channel with lots of videos."',
            '--email="creator@smallmedia.com"', '--tags=music', '--tags=art',
            '--languages=pt-BR', '--languages=uk', '--locations=BR', '--locations=UA::Kiyv',
            '--website_url="http://smallmedia.com"', '--thumbnail_url="http://smallmedia.com/logo.jpg"',
            '--cover_url="http://smallmedia.com/logo.jpg"'
        )
        await self.on_transaction_dict(big_channel)
        await self.generate(1)
        await self.on_transaction_dict(big_channel)
        await self.daemon.jsonrpc_channel_abandon(big_channel['outputs'][0]['claim_id'])
        await self.generate(1)

        # stream claims

        with tempfile.NamedTemporaryFile() as file:
            file.write(b'hello world')
            file.flush()
            stream = await r(
                'Create a stream claim without metadata',
                'stream', 'create', 'astream', '1.0', file.name
            )
            await self.on_transaction_dict(stream)
            await self.generate(1)
            await self.on_transaction_dict(stream)
        stream_id = stream['outputs'][0]['claim_id']
        stream_name = stream['outputs'][0]['name']
        stream = await r(
            'Update a stream claim to add channel',
            'stream', 'update', stream_id,
            f'--channel_id="{channel_id}"'
        )
        await self.on_transaction_dict(stream)
        await self.generate(1)
        await self.on_transaction_dict(stream)

        await r(
            'List all your claims',
            'claim', 'list'
        )

        await r(
            'Paginate your claims',
            'claim', 'list', '--page=1', '--page_size=20'
        )

        await r(
            'List all your stream claims',
            'stream', 'list'
        )

        await r(
            'Paginate your stream claims',
            'stream', 'list', '--page=1', '--page_size=20'
        )

        await r(
            'Search for all claims in channel',
            'claim', 'search', '--channel=@channel'
        )

        await r(
            'Search for claims matching a name',
            'claim', 'search', f'--name="{stream_name}"'
        )

        with tempfile.NamedTemporaryFile(suffix='.png') as file:
            file.write(unhexlify(
                b'89504e470d0a1a0a0000000d49484452000000050000000708020000004fc'
                b'510b9000000097048597300000b1300000b1301009a9c1800000015494441'
                b'5408d763fcffff3f031260624005d4e603004c45030b5286e9ea000000004'
                b'9454e44ae426082'
            ))
            file.flush()
            big_stream = await r(
                'Create an image stream claim with all metadata and fee',
                'stream', 'create', 'blank-image', '1.0', file.name,
                '--tags=blank', '--tags=art', '--languages=en', '--locations=US:NH:Manchester',
                '--fee_currency=LBC', '--fee_amount=0.3',
                '--title="Blank Image"', '--description="A blank PNG that is 5x7."', '--author=Picaso',
                '--license="Public Domain"', '--license_url=http://public-domain.org',
                '--thumbnail_url="http://smallmedia.com/thumbnail.jpg"', f'--release_time={int(time.time())}',
                f'--channel_id="{channel_id}"'
            )
            await self.on_transaction_dict(big_stream)
            await self.generate(1)
            await self.on_transaction_dict(big_stream)
            await self.daemon.jsonrpc_channel_abandon(big_stream['outputs'][0]['claim_id'])
            await self.generate(1)

        # files

        file_list_result = await r(
            'List local files',
            'file', 'list'
        )
        file_uri = f"{file_list_result[0]['claim_name']}#{file_list_result[0]['claim_id']}"
        await r(
            'Resolve a claim',
            'resolve', file_uri
        )

        await r(
            'List files matching a parameter',
            'file', 'list', f"--claim_id=\"{file_list_result[0]['claim_id']}\""
        )

        await r(
            'Delete a file',
            'file', 'delete', f"--claim_id=\"{file_list_result[0]['claim_id']}\""
        )

        await r(
            'Get a file',
            'get', file_uri
        )

        await r(
            'Save a file to the downloads directory',
            'file', 'save', f"--sd_hash=\"{file_list_result[0]['sd_hash']}\""
        )

        # blobs

        bloblist = await r(
            'List your local blobs',
            'blob', 'list'
        )

        await r(
            'Delete a blob',
            'blob', 'delete', f"{bloblist[0]}"
        )

        # abandon all the things

        abandon_stream = await r(
            'Abandon a stream claim',
            'stream', 'abandon', stream_id
        )
        await self.on_transaction_dict(abandon_stream)
        await self.generate(1)
        await self.on_transaction_dict(abandon_stream)

        abandon_channel = await r(
            'Abandon a channel claim',
            'channel', 'abandon', channel_id
        )
        await self.on_transaction_dict(abandon_channel)
        await self.generate(1)
        await self.on_transaction_dict(abandon_channel)

        with tempfile.NamedTemporaryFile() as file:
            file.write(b'hello world')
            file.flush()
            stream = await r(
                'Publish a file',
                'publish', 'a-new-stream', '--bid=1.0', f'--file_path={file.name}'
            )
            await self.on_transaction_dict(stream)
            await self.generate(1)
            await self.on_transaction_dict(stream)


def get_examples():
    player = Examples('play')
    result = player.run()
    if result.errors:
        for error in result.errors:
            print(error[1])
        raise Exception('See above for errors while running the examples.')
    return player.recorder.examples


SECTIONS = re.compile("(.*?)Usage:(.*?)Options:(.*?)Returns:(.*)", re.DOTALL)
REQUIRED_OPTIONS = re.compile("\(<(.*?)>.*?\)")
ARGUMENT_NAME = re.compile("--([^=]+)")
ARGUMENT_TYPE = re.compile("\s*\((.*?)\)(.*)")


def get_return_def(returns):
    result = returns.strip()
    if (result[0], result[-1]) == ('{', '}'):
        obj_type = result[1:-1]
        if '[' in obj_type:
            sub_type = obj_type[obj_type.index('[')+1:-1]
            obj_type = obj_type[:obj_type.index('[')]
            if obj_type == 'Paginated':
                obj_def = encode_pagination_doc(RETURN_DOCS[sub_type])
            elif obj_type == 'List':
                obj_def = [RETURN_DOCS[sub_type]]
            else:
                raise NameError(f'Unknown return type: {obj_type}')
        else:
            obj_def = RETURN_DOCS[obj_type]
        return indent(json.dumps(obj_def, indent=4), ' '*12)
    return result


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
        'returns': get_return_def(returns),
        'examples': examples
    }


def write_api(f):
    examples = get_examples()
    api_definitions = Daemon.get_api_definitions()
    apis = {
        'main': {
            'doc': 'Ungrouped commands.',
            'commands': []
        }
    }
    for group_name, group_doc in api_definitions['groups'].items():
        apis[group_name] = {
            'doc': group_doc,
            'commands': []
        }
    for method_name, command in api_definitions['commands'].items():
        if 'replaced_by' in command:
            continue
        apis[command['group'] or 'main']['commands'].append(get_api(
            method_name,
            examples.get(method_name, [])
        ))
    json.dump(apis, f, indent=4)


if __name__ == '__main__':
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html_file = os.path.join(parent, 'docs', 'api.json')
    with open(html_file, 'w+') as f:
        write_api(f)
