import sys
import os
import re
import logging
import lbry.build_info as build_info_mod

log = logging.getLogger()
log.addHandler(logging.StreamHandler())
log.setLevel(logging.DEBUG)


def _check_and_set(d: dict, key: str, value: str):
    try:
        d[key]
    except KeyError:
        raise Exception(f"{key} var does not exist in {build_info_mod.__file__}")
    d[key] = value


def main():
    build_info = {item: build_info_mod.__dict__[item] for item in dir(build_info_mod) if not item.startswith("__")}

    commit_hash = os.getenv('DOCKER_COMMIT', os.getenv('GITHUB_SHA'))
    if commit_hash is None:
        raise ValueError("Commit hash not found in env vars")
    _check_and_set(build_info, "COMMIT_HASH", commit_hash[:6])

    docker_tag = os.getenv('DOCKER_TAG')
    if docker_tag:
        _check_and_set(build_info, "DOCKER_TAG", docker_tag)
        _check_and_set(build_info, "BUILD", "docker")
    else:
        if re.match(r'refs/tags/v\d+\.\d+\.\d+$', str(os.getenv('GITHUB_REF'))):
            _check_and_set(build_info, "BUILD", "release")
        else:
            _check_and_set(build_info, "BUILD", "qa")

    log.debug("build info: %s", ", ".join([f"{k}={v}" for k, v in build_info.items()]))
    with open(build_info_mod.__file__, 'w') as f:
        f.write("\n".join([f"{k} = \"{v}\"" for k, v in build_info.items()]) + "\n")


if __name__ == '__main__':
    sys.exit(main())
