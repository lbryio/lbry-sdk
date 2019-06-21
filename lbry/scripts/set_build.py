"""Set the build version to be 'qa', 'rc', 'release'"""

import sys
import os
import re
import logging

log = logging.getLogger()
log.addHandler(logging.StreamHandler())
log.setLevel(logging.DEBUG)


def get_build_type(travis_tag=None):
    if not travis_tag:
        return "qa"
    log.debug("getting build type for tag: \"%s\"", travis_tag)
    if re.match('v\d+\.\d+\.\d+rc\d+$', travis_tag):
        return 'rc'
    elif re.match('v\d+\.\d+\.\d+$', travis_tag):
        return 'release'
    return 'qa'


def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    build_type_path = os.path.join(root_dir, 'lbry', 'build_type.py')
    log.debug("configuring build type file: %s", build_type_path)
    travis_commit = os.environ['TRAVIS_COMMIT'][:6]
    build_type = get_build_type(os.environ.get('TRAVIS_TAG', None))
    log.debug("setting build type=%s, build commit=%s", build_type, travis_commit)
    with open(build_type_path, 'w') as f:
        f.write("BUILD = \"{}\"\nBUILD_COMMIT = \"{}\"\n".format(build_type, travis_commit))


if __name__ == '__main__':
    sys.exit(main())
