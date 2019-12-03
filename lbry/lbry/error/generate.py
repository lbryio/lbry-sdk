import re
from textwrap import fill, indent


CLASS = """
class {name}Error({parent}Error):{doc}
    log_level = {log_level}
"""

INIT = """\
    def __init__({args}):
        super().__init__({format}"{desc}")
"""

INDENT = ' ' * 4


def main():
    with open('README.md', 'r') as readme:
        lines = readme.readlines()
        for line in lines:
            if line.startswith('## Error Table'):
                break
        print('from .base import BaseError\n')
        stack = {}
        started = False
        for line in lines:
            if not started:
                started = line.startswith('---:|')
                continue
            if not line:
                break
            parent = 'Base'
            h, log_level, code, desc = [c.strip() for c in line.split('|')]
            comment = ""
            if '--' in desc:
                desc, comment = [s.strip() for s in desc.split('--')]
            log_level += "0"
            if h.startswith('**'):
                if h.count('x') == 1:
                    parent = stack[h[2:3]][0]
                stack[h.replace('**', '').replace('x', '')] = (code, desc)
                if h.count('x') == 2:
                    stack[h.replace('**', '').replace('x', '')+'0'] = (code, desc)
                comment = f'\n{INDENT}"""\n{indent(fill(comment or desc, 100), INDENT)}\n{INDENT}"""'
                print(CLASS.format(name=code, parent=parent, doc=comment, log_level=log_level))
                continue
            parent = stack[h[:2]][0]
            args = ['self']
            for arg in re.findall('{([a-z0-1]+)}', desc):
                args.append(arg)
            fmt = ""
            if len(args) > 1:
                fmt = "f"
            if comment:
                comment = f'\n{INDENT}"""\n{indent(fill(comment, 100), INDENT)}\n{INDENT}"""'
            print((CLASS+INIT).format(
                name=code, parent=parent, args=', '.join(args), log_level=log_level,
                desc=desc, doc=comment, format=fmt
            ))


if __name__ == "__main__":
    main()
