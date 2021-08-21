import re
import sys
import argparse
from pathlib import Path
from textwrap import fill, indent


INDENT = ' ' * 4

CLASS = """

class {name}({parents}):{doc}
"""

INIT = """
    def __init__({args}):{fields}
        super().__init__({format}"{message}")
"""

FUNCTIONS = ['claim_id']


class ErrorClass:

    def __init__(self, hierarchy, name, message):
        self.hierarchy = hierarchy.replace('**', '')
        self.other_parents = []
        if '(' in name:
            assert ')' in name, f"Missing closing parenthesis in '{name}'."
            self.other_parents = name[name.find('(')+1:name.find(')')].split(',')
            name = name[:name.find('(')]
        self.name = name
        self.class_name = name+'Error'
        self.message = message
        self.comment = ""
        if '--' in message:
            self.message, self.comment = message.split('--')
        self.message = self.message.strip()
        self.comment = self.comment.strip()

    @property
    def is_leaf(self):
        return 'x' not in self.hierarchy

    @property
    def code(self):
        return self.hierarchy.replace('x', '')

    @property
    def parent_codes(self):
        return self.hierarchy[0:2], self.hierarchy[0]

    def get_arguments(self):
        args = ['self']
        for arg in re.findall('{([a-z0-1_()]+)}', self.message):
            for func in FUNCTIONS:
                if arg.startswith(f'{func}('):
                    arg = arg[len(f'{func}('):-1]
                    break
            args.append(arg)
        return args

    @staticmethod
    def get_fields(args):
        if len(args) > 1:
            return ''.join(f'\n{INDENT*2}self.{field} = {field}' for field in args[1:])
        return ''

    @staticmethod
    def get_doc_string(doc):
        if doc:
            return f'\n{INDENT}"""\n{indent(fill(doc, 100), INDENT)}\n{INDENT}"""'
        return ""

    def render(self, out, parent):
        if not parent:
            parents = ['BaseError']
        else:
            parents = [parent.class_name]
        parents += self.other_parents
        args = self.get_arguments()
        if self.is_leaf:
            out.write((CLASS + INIT).format(
                name=self.class_name, parents=', '.join(parents),
                args=', '.join(args), fields=self.get_fields(args),
                message=self.message, doc=self.get_doc_string(self.comment), format='f' if len(args) > 1 else ''
            ))
        else:
            out.write(CLASS.format(
                name=self.class_name, parents=', '.join(parents),
                doc=self.get_doc_string(self.comment or self.message)
            ))


def get_errors():
    with open('README.md', 'r') as readme:
        lines = iter(readme.readlines())
        for line in lines:
            if line.startswith('## Exceptions Table'):
                break
        for line in lines:
            if line.startswith('---:|'):
                break
        for line in lines:
            if not line:
                break
            yield ErrorClass(*[c.strip() for c in line.split('|')])


def find_parent(stack, child):
    for parent_code in child.parent_codes:
        parent = stack.get(parent_code)
        if parent:
            return parent


def generate(out):
    out.write(f"from .base import BaseError, {', '.join(FUNCTIONS)}\n")
    stack = {}
    for error in get_errors():
        error.render(out, find_parent(stack, error))
        if not error.is_leaf:
            assert error.code not in stack, f"Duplicate code: {error.code}"
            stack[error.code] = error


def analyze():
    errors = {e.class_name: [] for e in get_errors() if e.is_leaf}
    here = Path(__file__).absolute().parents[0]
    module = here.parent
    for file_path in module.glob('**/*.py'):
        if here in file_path.parents:
            continue
        with open(file_path) as src_file:
            src = src_file.read()
            for error in errors.keys():
                found = src.count(error)
                if found > 0:
                    errors[error].append((file_path, found))

    print('Unused Errors:\n')
    for error, used in errors.items():
        if used:
            print(f' - {error}')
            for use in used:
                print(f'   {use[0].relative_to(module.parent)} {use[1]}')
            print('')

    print('')
    print('Unused Errors:')
    for error, used in errors.items():
        if not used:
            print(f' - {error}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=['generate', 'analyze'])
    args = parser.parse_args()
    if args.action == "analyze":
        analyze()
    elif args.action == "generate":
        generate(sys.stdout)


if __name__ == "__main__":
    main()
