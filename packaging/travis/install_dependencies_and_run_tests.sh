#!/bin/bash
#
# This script is used by travis to install lbry from source
#

set -euo pipefail
set -o xtrace

SUDO=''
if (( $EUID != 0 )); then
    SUDO='sudo'
fi

if [ -z ${TRAVIS+x} ]; then
  # if not on travis, its nice to see progress
  QUIET=""
else
    QUIET="-qq"
fi

# get the required OS packages
$SUDO apt-get ${QUIET} update
$SUDO apt-get ${QUIET} install -y --no-install-recommends \
      build-essential python-dev libffi-dev libssl-dev git \
      libgmp3-dev wget ca-certificates python-virtualenv

# create a virtualenv so we don't muck with anything on the system
virtualenv venv
# need to unset these or else we can't activate
set +eu
source venv/bin/activate
set -eu

# need a modern version of pip (more modern than ubuntu default)
wget https://bootstrap.pypa.io/get-pip.py
python get-pip.py
rm get-pip.py

pip install -r requirements.txt
pip install cython
pip install unqlite

pip install mock pylint coveralls
# have to do `which trial` instead of simply trial because coverage needs the full path
# trial, strangely, requires that the package be installed, which we don't want
# so we have to hack the PYTHONPATH to allow it to find lbry and tests
PYTHONPATH="." coverage run --source=lbrynet `which trial` tests
coveralls

./run_pylint.sh
