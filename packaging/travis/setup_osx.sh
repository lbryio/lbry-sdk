#!/bin/sh

set -euo pipefail
set -o xtrace

wget https://www.python.org/ftp/python/2.7.11/python-2.7.11-macosx10.6.pkg
sudo installer -pkg python-2.7.11-macosx10.6.pkg -target /
pip install -U pip
brew update

# follow this pattern to avoid failing if its already
# installed by brew:
# http://stackoverflow.com/a/20802425
if brew ls --versions gmp > /dev/null; then
    echo 'gmp is already installed by brew'
else
    brew install gmp
fi

if brew ls --versions openssl > /dev/null; then
    echo 'openssl is already installed by brew'
else
    brew install openssl
    brew link --force openssl
fi
