import re


CLASS = """
class {name}Error({parent}Error):{doc}

    def __init__({args}):
        super().__init__(f'{desc}')
"""

INDENT = ' ' * 4


def main():
    with open('README.md', 'r') as readme:
        stack = {}
        started = False
        for line in readme.readlines():
            if not started:
                started = line.startswith('---:|')
                continue
            if not line:
                break
            parent = 'Base'
            columns = [c.strip() for c in line.split('|')]
            (h, code, desc), comment = columns[:3], ""
            if len(columns) == 4:
                comment = columns[3]
            if h.startswith('**'):
                if h.count('x') == 1:
                    parent = stack[h[2:3]][0]
                stack[h.replace('**', '').replace('x', '')] = (code, desc)
            else:
                parent = stack[h[:2]][0]
            args = ['self']
            for arg in re.findall('{([a-z0-1]+)}', desc):
                args.append(arg)
            if comment:
                comment = f'\n{INDENT}"""\n{INDENT}{comment}\n{INDENT}"""'
            print(CLASS.format(name=code, parent=parent, args=', '.join(args), desc=desc, doc=comment))


if __name__ == "__main__":
    main()
