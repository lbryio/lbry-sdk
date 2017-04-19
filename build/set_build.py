"""Set the build version to be 'dev', 'qa', 'rc', 'release'"""

import os.path
import re
import subprocess
import sys


def main():
    build = get_build()
    root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    with open(os.path.join(root_dir, 'lbrynet', 'build_type.py'), 'w') as f:
        f.write("BUILD = '{}'\n".format(build))


def get_build():
    try:
        tag = subprocess.check_output(['git', 'describe', '--exact-match']).strip()
        if re.match('v\d+\.\d+\.\d+rc\d+', tag):
            return 'rc'
        else:
            return 'release'
    except subprocess.CalledProcessError:
        # if the build doesn't have a tag
        return 'qa'


if __name__ == '__main__':
    sys.exit(main())
