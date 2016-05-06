#!/bin/bash

# Tested on fresh Ubuntu 14.04 install.

# wget https://raw.githubusercontent.com/lbryio/lbry/master/packaging/ubuntu/ubuntu_package_setup.sh
# bash ubuntu_package_setup.sh [BRANCH] [WEB-UI-BRANCH]

set -euo pipefail

BRANCH=${1:-master}
WEB_UI_BRANCH=${2:-}

BUILD_DIR="lbry-build-$(date +%Y%m%d-%H%M%S)"
mkdir "$BUILD_DIR"
cd "$BUILD_DIR"

# get the required OS packages
sudo add-apt-repository -y ppa:spotify-jyrki/dh-virtualenv
sudo apt-get update
sudo apt-get install -y build-essential git python-dev libffi-dev libssl-dev libgmp3-dev dh-virtualenv debhelper

# need a modern version of pip (more modern than ubuntu default)
wget https://bootstrap.pypa.io/get-pip.py
sudo python get-pip.py
rm get-pip.py
sudo pip install make-deb

# check out LBRY
git clone https://github.com/lbryio/lbry.git --branch "$BRANCH"

# build packages
(
  cd lbry
  make-deb
  dpkg-buildpackage -us -uc
)


### insert our extra files

# extract .deb
PACKAGE="$(ls | grep '.deb')"
ar vx "$PACKAGE"
mkdir control data
tar -xvzf control.tar.gz --directory control
tar -xvJf data.tar.xz --directory data

PACKAGING_DIR='lbry/packaging/ubuntu'

# set web ui branch
if [ -z "$WEB_UI_BRANCH" ]; then
  sed -i "s/^WEB_UI_BRANCH='[^']\+'/WEB_UI_BRANCH='$WEB_UI_BRANCH'/" "$PACKAGING_DIR/lbry"
fi

# add files
function addfile() {
  FILE="$1"
  TARGET="$2"
  mkdir -p "$(dirname "data/$TARGET")"
  cp "$FILE" "data/$TARGET"
  echo "$(md5sum "data/$TARGET" | cut -d' ' -f1)  $TARGET" >> control/md5sums
}
addfile "$PACKAGING_DIR/lbry" usr/share/python/lbrynet/bin/lbry
addfile "$PACKAGING_DIR/lbry.desktop" usr/share/applications/lbry.desktop
#addfile lbry/packaging/ubuntu/lbry-init.conf etc/init/lbry.conf

# repackage .deb
sudo chown -R root:root control data
tar -cvzf control.tar.gz -C control .
tar -cvJf data.tar.xz -C data .
sudo chown root:root debian-binary control.tar.gz data.tar.xz
ar r "$PACKAGE" debian-binary control.tar.gz data.tar.xz

# TODO: we can append to data.tar instead of extracting it all and recompressing
