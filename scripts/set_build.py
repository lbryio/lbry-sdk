"""Set the build version to be 'qa', 'rc', 'release'"""

import sys
import os
import re


def get_build_type(travis_tag=None):
    if not travis_tag:
        return "qa"
    print("getting build type for tag: \"%s\"" % travis_tag)
    if re.match('v\d+\.\d+\.\d+rc\d+$', travis_tag):
        return 'rc'
    elif re.match('v\d+\.\d+\.\d+$', travis_tag):
        return 'release'
    return 'qa'


def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    travis_commit = os.environ['TRAVIS_COMMIT'][:6]
    build_type = get_build_type(os.environ.get('TRAVIS_TAG', None))
    print("setting build type=%s, build commit=%s", build_type, travis_commit)
    with open(os.path.join(root_dir, 'lbrynet', 'build_type.py'), 'w') as f:
        f.write("BUILD = \"{}\"\nBUILD_COMMIT = \"{}\"\n".format(build_type, travis_commit))


if __name__ == '__main__':
    sys.exit(main())
