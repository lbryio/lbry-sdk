"""Set the build version to be 'qa', 'rc', 'release'"""

import sys
import os
import re
import logging

log = logging.getLogger()
log.addHandler(logging.StreamHandler())
log.setLevel(logging.DEBUG)


def get_build_type(ci_tag=None):
    if not ci_tag:
        return "qa"
    log.debug("getting build type for tag: \"%s\"", ci_tag)
    if re.match(r'v\d+\.\d+\.\d+rc\d+$', ci_tag):
        return 'rc'
    elif re.match(r'v\d+\.\d+\.\d+$', ci_tag):
        return 'release'
    return 'qa'


def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    build_type_path = os.path.join(root_dir, 'lbry', 'build_type.py')
    log.debug("configuring build type file: %s", build_type_path)
    commit_hash = os.getenv('CI_COMMIT_SHA', os.getenv('TRAVIS_COMMIT', None))[:6]
    build_type = get_build_type(os.getenv('CI_COMMIT_TAG', os.getenv('TRAVIS_TAG', None)))
    log.debug("setting build type=%s, build commit=%s", build_type, commit_hash)
    with open(build_type_path, 'w') as f:
        f.write(f"BUILD = \"{build_type}\"\nBUILD_COMMIT = \"{commit_hash}\"\n")


if __name__ == '__main__':
    sys.exit(main())
