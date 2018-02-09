#!/bin/bash

set -euo pipefail
set -x


LINUX=false
OSX=false

if [ "$(uname)" == "Darwin" ]; then
  OSX=true
elif [ "$(expr substr $(uname -s) 1 5)" == "Linux" ]; then
  LINUX=true
else
  echo "Platform detection failed"
  exit 1
fi


SUDO=''
if $LINUX && (( $EUID != 0 )); then
    SUDO='sudo'
fi

cmd_exists() {
  command -v "$1" >/dev/null 2>&1
  return $?
}

set +eu
GITUSERNAME=$(git config --global --get user.name)
if [ -z "$GITUSERNAME" ]; then
  git config --global user.name "$(whoami)"
fi
GITEMAIL=$(git config --global --get user.email)
if [ -z "$GITEMAIL" ]; then
  git config --global user.email "$(whoami)@lbry.io"
fi
set -eu


if $LINUX; then
  INSTALL="$SUDO apt-get install --no-install-recommends -y"
  $INSTALL build-essential libssl-dev libffi-dev python2.7-dev wget
elif $OSX && ! cmd_exists brew ; then
  /usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
fi


if ! cmd_exists python; then
  if $LINUX; then
    $INSTALL python2.7
  elif $OSX; then
    brew install python
  fi
fi

PYTHON_VERSION=$(python -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
if [ "$PYTHON_VERSION" != "2.7" ]; then
  echo "Python 2.7 required"
  exit 1
fi

if ! cmd_exists pip; then
  if $LINUX; then
    $INSTALL python-pip
    $SUDO pip install --upgrade pip
  else
    echo "Pip required"
    exit 1
  fi
fi

if $LINUX && [ "$(pip list --format=columns | grep setuptools | wc -l)" -ge 1 ]; then
  #$INSTALL python-setuptools
  $SUDO pip install setuptools
fi

if ! cmd_exists virtualenv; then
  $SUDO pip install virtualenv
fi
