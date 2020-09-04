import json
import inspect
import textwrap
import tokenize
import token
from io import BytesIO
from typing import Tuple, List

from lbry.service import api
from lbry.service import json_encoder


LINE_WIDTH = 90


def parse_description(desc) -> dict:
    lines = iter(desc.splitlines())
    parts = {'text': []}
    current = parts['text']
    for line in lines:
        if line.strip() in ('Usage:', 'Options:', 'Returns:'):
            current = parts.setdefault(line.strip().lower()[:-1], [])
        else:
            if line.strip():
                if line.strip() == '{kwargs}':
                    parts['kwargs'] = line.find('{kwargs}')
                else:
                    current.append(line)
    return parts


def parse_type(tokens: List) -> Tuple[str, str]:
    type_ = [tokens.pop(0).string]
    if tokens and tokens[0].string == '[':
        while tokens[0].string != ']':
            type_.append(tokens.pop(0).string)
        type_.append(tokens.pop(0).string)
    json_ = None
    if type_ == ['StrOrList']:
        type_ = ['str, list']
    elif type_[0] == 'Paginated':
        json_ = json_encoder.encode_pagination_doc(
            getattr(json_encoder, f'{type_[2].lower()}_doc')
        )
    elif len(type_) == 1 and hasattr(json_encoder, f'{type_[0].lower()}_doc'):
        json_ = getattr(json_encoder, f'{type_[0].lower()}_doc')
    return ''.join(type_), json_


def parse_argument(tokens, method_name='') -> dict:
    arg = {
        'name': tokens.pop(0).string,
        'desc': []
    }
    if arg['name'] == 'self':
        return {}
    if tokens[0].string == ':':
        tokens.pop(0)
        type_tokens = []
        while tokens[0].string not in ('=', ',', ')') and tokens[0].type != token.COMMENT:
            type_tokens.append(tokens.pop(0))
        arg['type'] = parse_type(type_tokens)[0]
    if tokens[0].string == '=':
        tokens.pop(0)
        default = tokens.pop(0)
        if default.type == token.NAME:
            default_value = eval(default.string)  # pylint: disable=eval-used
            if default_value is not None:
                arg['default'] = default_value
        elif default.type == token.NUMBER:
            arg['default'] = int(default.string)
        else:
            arg['default'] = default.string
    if tokens[0].string == ',':
        tokens.pop(0)
    if 'type' not in arg:
        if 'default' in arg:
            arg['type'] = type(arg['default']).__name__
        else:
            raise Exception(f"No type and no default value for {arg['name']} in {method_name}")
    for part in tokens:
        if part.type == token.COMMENT:
            arg['desc'].append(part.string[1:].strip())
    return arg


def produce_argument_tokens(src: str):
    in_args = False
    in_comment = False
    parsed = []
    for t in tokenize.tokenize(BytesIO(src.encode()).readline):
        if t.string == '(':
            in_args = True
        elif in_args:
            if not in_comment and t.string == ',':
                in_comment = True
            elif in_comment and (t.type == token.NAME or t.string == '**'):
                if not parsed[0].string.startswith('_'):
                    yield parsed
                in_comment = False
                parsed = []
            if t.type in (token.NAME, token.OP, token.COMMENT, token.STRING, token.NUMBER):
                parsed.append(t)
            if t.string == ')':
                if not parsed[0].string.startswith('_'):
                    yield parsed
                break


def parse_return(tokens) -> dict:
    d = {'desc': [], 'type': None}
    if tokens[0].string == '->':
        tokens.pop(0)
        type_tokens = []
        while tokens[0].string != ':':
            type_tokens.append(tokens.pop(0))
        d['type'], _ = parse_type(type_tokens)
        if _:
            d['json'] = _
    assert tokens.pop(0).string == ':'
    for part in tokens:
        if part.type == token.COMMENT:
            d['desc'].append(part.string[1:].strip())
    return d


def produce_return_tokens(src: str):
    in_return = False
    parsed = []
    for t in tokenize.tokenize(BytesIO(src.encode()).readline):
        if t.string == ')':
            in_return = True
        elif in_return:
            if t.type == token.INDENT:
                break
            parsed.append(t)
    return parsed


def parse_method(method, expanders: dict) -> dict:
    d = {
        'name': method.__name__,
        'desc': parse_description(textwrap.dedent(method.__doc__)) if method.__doc__ else {},
        'method': method,
        'arguments': [],
        'returns': None
    }
    src = inspect.getsource(method)
    known_names = set()
    for tokens in produce_argument_tokens(src):
        if tokens[0].string == '**':
            tokens.pop(0)
            d['kwargs'] = []
            expander_names = tokens.pop(0).string[:-7]
            if expander_names.startswith('_'):
                continue
            for expander_name in expander_names.split('_and_'):
                if expander_name not in expanders:
                    raise Exception(f"Expander '{expander_name}' not found, used by {d['name']}.")
                for expanded in expanders[expander_name]:
                    if expanded['name'] in known_names:
                        raise Exception(f"Expander '{expander_name}' argument repeated: {expanded['name']}.")
                    d['arguments'].append(expanded)
                    d['kwargs'].append(expanded)
                    known_names.add(expanded['name'])
        else:
            arg = parse_argument(tokens, d['name'])
            if arg:
                d['arguments'].append(arg)
                known_names.add(arg['name'])
    d['returns'] = parse_return(produce_return_tokens(src))
    return d


def get_expanders():
    expanders = {}
    for name, func in api.kwarg_expanders.items():
        if name.endswith('_original'):
            expanders[name[:-len('_original')]] = parse_method(func, expanders)['arguments']
    return expanders


def get_groups(cls):
    return {
        group_name[:-len('_DOC')].lower(): getattr(cls, group_name).strip()
        for group_name in dir(cls) if group_name.endswith('_DOC')
    }


def get_methods(cls):
    expanders = get_expanders()
    return {
        method: parse_method(getattr(cls, method), expanders)
        for method in dir(cls) if not method.endswith('_DOC') and not method.startswith('_')
    }


def generate_options(method, indent) -> List[str]:
    if not method['arguments']:
        return []
    flags = []
    for arg in method['arguments']:
        if arg['type'] == 'bool':
            flags.append(f"--{arg['name']}")
        else:
            flags.append(f"--{arg['name']}=<{arg['name']}>")
    max_len = max(len(f) for f in flags) + 2
    flags = [f.ljust(max_len) for f in flags]
    options = []
    for flag, arg in zip(flags, method['arguments']):
        left = f"{indent}{flag}: "
        text = f"({arg['type']}) {' '.join(arg['desc'])}"
        if 'default' in arg:
            if arg['type'] != 'bool':
                text += f" [default: {arg['default']}]"
        wrapped = textwrap.wrap(text, LINE_WIDTH-len(left))
        lines = [f"{left}{wrapped.pop(0)}"]
        # dont break on -- or docopt will parse as a new option
        for line_number, line in enumerate(wrapped):
            if line.strip().startswith('--'):
                raise Exception(f"Continuation line starts with -- on {method['cli']}: \"{line.strip()}\"")
            lines.append(f"{' ' * len(left)} {line}")
        options.extend(lines)
    return options


def generate_help(command):
    indent = 4
    text = []
    desc = command['desc']

    for line in desc.get('text', []):
        text.append(line)
    text.append('')

    usage, kwargs_offset = desc.get('usage', []), desc.get('kwargs', False)
    text.append('Usage:')
    if usage:
        for line in usage:
            text.append(line)
    else:
        text.append(f"{' '*indent}{command['cli']}")
    if kwargs_offset:
        flags = []
        for arg in command['kwargs']:
            if arg['type'] == 'bool':
                flags.append(f"[--{arg['name']}]")
            elif 'list' in arg['type']:
                flags.append(f"[--{arg['name']}=<{arg['name']}>...]")
            else:
                flags.append(f"[--{arg['name']}=<{arg['name']}>]")
        wrapped = textwrap.wrap(' '.join(flags), LINE_WIDTH-kwargs_offset)
        for line in wrapped:
            text.append(f"{' '*kwargs_offset}{line}")
    text.append('')

    options = desc.get('options', [])
    if options or command['arguments']:
        text.append('Options:')
        for line in options:
            text.append(line)
        text.extend(generate_options(command, ' '*indent))
        text.append('')

    returns = desc.get('returns', [])
    if returns or command['returns']['type']:
        text.append('Returns:')
        if command['returns']['type']:
            return_comment = ' '.join(command['returns']['desc'])
            text.append(f"{' '*indent}({command['returns']['type']}) {return_comment}")
        text.extend(returns)
        if 'json' in command['returns']:
            dump = json.dumps(command['returns']['json'], indent=4)
            text.extend(textwrap.indent(dump, ' '*indent).splitlines())

    return '\n'.join(text)


def get_api_definitions(cls):
    groups = get_groups(cls)
    commands = get_methods(cls)
    for name, command in commands.items():
        parts = name.split('_')
        if parts[0] in groups:
            command['name'] = '_'.join(parts[1:])
            command['group'] = parts[0]
            command['cli'] = f"{command['group']} {command['name']}"
        else:
            command['cli'] = command['name']
        command['help'] = generate_help(command)
    return {'groups': groups, 'commands': commands}


def write(fp):
    fp.write('# pylint: skip-file\n')
    fp.write('# DO NOT EDIT: GENERATED FILE\n')
    fp.write('interface = ')
    defs = get_api_definitions(api.API)
    for c in defs['commands'].values():
        del c['method']
    j = json.dumps(defs, indent=4)
    j = j.replace(': false', ': False')
    j = j.replace(': true', ': True')
    j = j.replace(': null', ': None')
    fp.write(j)
    fp.write('\n')


def main():
    with open('metadata.py', 'w') as fp:
        write(fp)


if __name__ == "__main__":
    main()
