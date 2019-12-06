import re
from textwrap import fill, indent


INDENT = ' ' * 4

CLASS = """

class {name}({parents}):{doc}
"""

INIT = """
    def __init__({args}):
        super().__init__({format}"{message}")
"""


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
        for arg in re.findall('{([a-z0-1]+)}', self.message):
            args.append(arg)
        return args

    def get_doc_string(self, doc):
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
                name=self.class_name, parents=', '.join(parents), args=', '.join(args),
                message=self.message, doc=self.get_doc_string(self.comment), format='f' if len(args) > 1 else ''
            ))
        else:
            out.write(CLASS.format(
                name=self.class_name, parents=', '.join(parents),
                doc=self.get_doc_string(self.comment or self.message)
            ))


def error_rows(lines):
    lines = iter(lines)
    for line in lines:
        if line.startswith('## Exceptions Table'):
            break
    for line in lines:
        if line.startswith('---:|'):
            break
    for line in lines:
        if not line:
            break
        yield line


def find_parent(stack, child):
    for parent_code in child.parent_codes:
        parent = stack.get(parent_code)
        if parent:
            return parent


def main(out):
    with open('README.md', 'r') as readme:
        lines = readme.readlines()
        out.write('from .base import BaseError\n')
        stack = {}
        for row in error_rows(lines):
            error = ErrorClass(*[c.strip() for c in row.split('|')])
            error.render(out, find_parent(stack, error))
            if not error.is_leaf:
                assert error.code not in stack, f"Duplicate code: {error.code}"
                stack[error.code] = error


if __name__ == "__main__":
    import sys
    main(sys.stdout)
