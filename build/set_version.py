"""Set the package version to the output of `git describe`"""

import argparse
import os.path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', help="defaults to the output of `git describe`")
    args = parser.parse_args()
    if args.version:
        version = args.version
    else:
        tag = subprocess.check_output(['git', 'describe']).strip()
        try:
            version = get_version_from_tag(tag)
        except InvalidVersionTag:
            # this should be an error but its easier to handle here
            # than in the calling scripts.
            print 'Tag cannot be converted to a version. Exiting.'
            return
    set_version(version)


class InvalidVersionTag(Exception):
    pass


def get_version_from_tag(tag):
    match = re.match('v([\d.]+)', tag)
    if match:
        return match.group(1)
    else:
        raise InvalidVersionTag('Failed to parse version from tag {}'.format(tag))


def set_version(version):
    root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    with open(os.path.join(root_dir, 'lbrynet', '__init__.py'), 'w') as fp:
        fp.write(LBRYNET_TEMPLATE.format(version=version))


LBRYNET_TEMPLATE = """
__version__ = "{version}"
version = tuple(__version__.split('.'))
"""

if __name__ == '__main__':
    sys.exit(main())
