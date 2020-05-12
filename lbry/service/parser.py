import json
import inspect
import textwrap
import tokenize
import token
from io import BytesIO
from typing import Tuple, List

from lbry.service import api
from lbry.service import json_encoder


def parse_description(desc) -> dict:
    lines = iter(desc.splitlines())
    parts = {'text': []}
    current = parts['text']
    for line in lines:
        if line.strip() in ('Usage:', 'Options:', 'Returns:'):
            current = parts.setdefault(line.strip().lower()[:-1], [])
        else:
            if line.strip():
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
    return ''.join(type_), json_
    #    obj_type = result[1:-1]
    #    if '[' in obj_type:
    #        sub_type = obj_type[obj_type.index('[') + 1:-1]
    #        obj_type = obj_type[:obj_type.index('[')]
    #        if obj_type == 'Paginated':
    #            obj_def = encode_pagination_doc(RETURN_DOCS[sub_type])
    #        elif obj_type == 'List':
    #            obj_def = [RETURN_DOCS[sub_type]]
    #        else:
    #            raise NameError(f'Unknown return type: {obj_type}')
    #    else:
    #        obj_def = RETURN_DOCS[obj_type]
    #    return indent(json.dumps(obj_def, indent=4), ' ' * 12)


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
            default_value = eval(default.string)
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
                yield parsed
                in_comment = False
                parsed = []
            if t.type in (token.NAME, token.OP, token.COMMENT, token.STRING, token.NUMBER):
                parsed.append(t)
            if t.string == ')':
                yield parsed
                break


def parse_return(tokens) -> dict:
    d = {'desc': []}
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
            else:
                parsed.append(t)
    return parsed


def parse_method(method, expanders: dict) -> dict:
    d = {
        'name': method.__name__,
        'desc': parse_description(textwrap.dedent(method.__doc__)) if method.__doc__ else '',
        'method': method,
        'arguments': [],
        'returns': None
    }
    src = inspect.getsource(method)
    for tokens in produce_argument_tokens(src):
        if tokens[0].string == '**':
            tokens.pop(0)
            expander_name = tokens.pop(0).string[:-7]
            if expander_name not in expanders:
                raise Exception(f"Expander '{expander_name}' not found, used by {d['name']}.")
            expander = expanders[expander_name]
            d['arguments'].extend(expander)
        else:
            arg = parse_argument(tokens, d['name'])
            if arg:
                d['arguments'].append(arg)
    d['returns'] = parse_return(produce_return_tokens(src))
    return d


def get_expanders():
    expanders = {}
    for e in api.kwarg_expanders:
        expanders[e.__name__] = parse_method(e, expanders)['arguments']
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


def generate_options(method, indent):
    flags = []
    for arg in method['arguments']:
        if arg['type'] == 'bool':
            flags.append(f"--{arg['name']}")
        else:
            flags.append(f"--{arg['name']}=<{arg['name']}>")
    max_len = max(len(f) for f in flags) + 1
    flags = [f.ljust(max_len) for f in flags]
    options = []
    for flag, arg in zip(flags, method['arguments']):
        line = [f"{indent}{flag}: ({arg['type']}) {' '.join(arg['desc'])}"]
        if 'default' in arg:
            line.append(f" [default: {arg['default']}]")
        options.append(''.join(line))
    return options


def augment_description(command):
    pass



def get_api_definitions(cls):
    groups = get_groups(cls)
    commands = get_methods(cls)
    for name, command in commands.items():
        parts = name.split('_')
        if parts[0] in groups:
            command['name'] = '_'.join(parts[1:])
            command['group'] = parts[0]
            #command['desc'] =
    return {'groups': groups, 'commands': commands}


def write(fp):
    fp.write('# DO NOT EDIT: GENERATED FILE\n')
    fp.write(f'interface = ')
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
