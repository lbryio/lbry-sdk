#!/bin/bash
#
# Configure the library for a non-production release
#

set -euo pipefail
set -o xtrace


# changes here also need to be added to build.ps1 for windows
python packaging/append_sha_to_version.py lbrynet/__init__.py ${TRAVIS_COMMIT}

wget https://s3.amazonaws.com/lbry-ui/development/dist.zip -O dist.zip
unzip -oq dist.zip -d lbrynet/resources/ui
wget https://s3.amazonaws.com/lbry-ui/development/data.json -O lbrynet/resources/ui/data.json
