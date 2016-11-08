#!/bin/sh

set -euo pipefail
set -o xtrace

wget https://www.python.org/ftp/python/2.7.11/python-2.7.11-macosx10.6.pkg
sudo installer -pkg python-2.7.11-macosx10.6.pkg -target /
pip install -U pip
brew install gmp
# GNU vs BSD sed handles in-place every so slightly different
# so its worth installing the GNU version
brew install gnu-sed --with-default-names
