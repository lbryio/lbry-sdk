import argparse
import re
import sys


def main(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument('commit')
    args = parser.parse_args(args)

    with open(args.filename) as f:
        contents = f.read()

    commit = args.commit[:7]

    new_contents = re.sub(
        r'^__version__ = [\'"](.*)[\'"]$',
        r'__version__ = "\1-{}"'.format(args.commit),
        contents,
        flags=re.MULTILINE,
    )

    with open(args.filename, 'w') as f:
        f.write(new_contents)


if __name__ == '__main__':
    sys.exit(main())
