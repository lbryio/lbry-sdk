#!/bin/bash

set -euo pipefail

function HELP {
    echo "Build a debian package for lbry"
    echo "-----"
    echo "When run without any arguments, this script expects the current directory"
    echo "to be the main lbry repo and it builds what is in that directory"
    echo
    echo "Optional arguments:"
    echo
    echo "-c: clone a fresh copy of the repo"
    echo "-b <branch>: use the specified branch of the lbry repo"
    echo "-w <web-ui-branch>: set the webui branch"
    echo "-d <build-dir>: specifiy the build directory"
    echo "-h: show help"
    echo "-t: turn trace on"
    exit 1
}

CLONE=false
BUILD_DIR=""
BRANCH=""
WEB_UI_BRANCH="master"

while getopts :hctb:w:d: FLAG; do
    case $FLAG in
	c)
	    CLONE=true
	    ;;
	b)
	    BRANCH=${OPTARG}
	    ;;
	w)
	    WEB_UI_BRANCH=${OPTARG}
	    ;;
	d)
	    BUILD_DIR=${OPTARG}
	    ;;
	t)
	    set -o xtrace
	    ;;
	h)
	    HELP
	    ;;
	\?) #unrecognized option - show help
	    echo "Option -$OPTARG not allowed."
	    HELP
	    ;;
	:)
	    echo "Option -$OPTARG requires an argument."
	    HELP
	    ;;
    esac
done

shift $((OPTIND-1))


SUDO=''
if (( $EUID != 0 )); then
    SUDO='sudo'
fi

if [ "$CLONE" = false ]; then
    if [ `basename $PWD` != "lbry" ]; then
	echo "Not currently in the lbry directory. Cowardly refusing to go forward"
	exit 1
    fi
    SOURCE_DIR=$PWD
fi

if [ -z "${BUILD_DIR}" ]; then
    if [ "$CLONE" = true ]; then
	# build in the current directory
	BUILD_DIR="lbry-build-$(date +%Y%m%d-%H%M%S)"
    else
	BUILD_DIR="../lbry-build-$(date +%Y%m%d-%H%M%S)"
    fi
fi

mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

if [ -z ${TRAVIS+x} ]; then
  # if not on travis, its nice to see progress
  QUIET=""
else
    QUIET="-qq"
fi

# get the required OS packages
$SUDO apt-get ${QUIET} update
$SUDO apt-get ${QUIET} install -y --no-install-recommends software-properties-common
$SUDO add-apt-repository -y ppa:spotify-jyrki/dh-virtualenv
$SUDO apt-get ${QUIET} update
$SUDO apt-get ${QUIET} install -y --no-install-recommends \
      build-essential git python-dev libffi-dev libssl-dev \
      libgmp3-dev dh-virtualenv debhelper wget python-pip fakeroot

# need a modern version of pip (more modern than ubuntu default)
$SUDO pip install --upgrade pip
$SUDO pip install make-deb

# build packages
#
# dpkg-buildpackage outputs its results into '..' so
# we need to move/clone lbry into the build directory
if [ "$CLONE" == true ]; then
    git clone https://github.com/lbryio/lbry.git
else
    cp -a $SOURCE_DIR lbry
fi
(
    cd lbry
    if [ -n "${BRANCH}" ]; then
	git checkout "${BRANCH}"
    fi
    make-deb
    dpkg-buildpackage -us -uc
)


### insert our extra files

# extract .deb
PACKAGE="$(ls | grep '.deb')"
ar vx "$PACKAGE"
mkdir control data
tar -xzf control.tar.gz --directory control

# The output of the travis build is a
# tar.gz and the output locally is tar.xz.
# Instead of having tar detect the compression used, we
# could update the config to output the same in either spot.
# Unfortunately, doing so requires editting some auto-generated
# files: http://linux.spiney.org/forcing_gzip_compression_when_building_debian_packages
tar -xf data.tar.?z --directory data

PACKAGING_DIR='lbry/packaging/ubuntu'

# set web ui branch
sed -i "s/^WEB_UI_BRANCH='[^']\+'/WEB_UI_BRANCH='$WEB_UI_BRANCH'/" "$PACKAGING_DIR/lbry"

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

cat "$PACKAGING_DIR/postinst_append" >> control/postinst

# repackage .deb
$SUDO chown -R root:root control data
tar -czf control.tar.gz -C control .
tar -cJf data.tar.xz -C data .
$SUDO chown root:root debian-binary control.tar.gz data.tar.xz
ar r "$PACKAGE" debian-binary control.tar.gz data.tar.xz

# TODO: we can append to data.tar instead of extracting it all and recompressing

if [[ ! -z "${TRAVIS_BUILD_DIR+x}" ]]; then
    # move it to a consistent place so that later it can be uploaded
    # to the github releases page
    mv "${PACKAGE}" "${TRAVIS_BUILD_DIR}/${PACKAGE}"
    # want to be able to check the size of the result in the log
    ls -l "${TRAVIS_BUILD_DIR}/${PACKAGE}"
fi
