#!/bin/bash
#
# Configure build-specific things
#

set -euo pipefail
set -o xtrace

# changes to this script also need to be added to build.ps1 for windows
add_ui() {
    wget https://s3.amazonaws.com/lbry-ui/development/dist.zip -O dist.zip
    unzip -oq dist.zip -d lbrynet/resources/ui
    wget https://s3.amazonaws.com/lbry-ui/development/data.json -O lbrynet/resources/ui/data.json
}

set_build() {
  local file="lbrynet/build_type.py"
  # cannot use 'sed -i' because BSD sed and GNU sed are incompatible
  sed 's/^\(BUILD = "\)[^"]\+\(".*\)$/\1'"${1}"'\2/' "$file" > tmpbuildfile
  mv -- tmpbuildfile "$file"
}

IS_RC_REGEX="v[[:digit:]]+\.[[:digit:]]+\.[[:digit:]]+-rc[[:digit:]]+"

if [[ -z "$TRAVIS_TAG" ]]; then
    python packaging/append_sha_to_version.py lbrynet/__init__.py "${TRAVIS_COMMIT}"
    add_ui
    set_build "qa"
elif [[ "$TRAVIS_TAG" =~ $IS_RC_REGEX ]]; then
    # If the tag looks like v0.7.6-rc0 then this is a tagged release candidate.
    add_ui
    set_build "rc"
else
    set_build "release"
fi
