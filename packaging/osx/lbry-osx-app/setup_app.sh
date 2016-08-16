#!/bin/bash

set -o errexit
set -o xtrace

DEST=`pwd`
tmp="${DEST}/build"
ON_TRAVIS=false

rm -rf build dist LBRY.app

pip install wheel dmgbuild jsonrpc
# the default py2app (v0.9) has a bug that is fixed in the head of /metachris/py2app
pip install git+https://github.com/metachris/py2app

mkdir -p $tmp
cd $tmp

echo "Updating lbrynet"
if [ -z ${TRAVIS_BUILD_DIR+x} ]; then
    # building locally
    git clone --depth 1 http://github.com/lbryio/lbry.git
    cd lbry
    LBRY="${tmp}/lbry"
else
    # building on travis
    ON_TRAVIS=true
    cd ${TRAVIS_BUILD_DIR}
    LBRY=${TRAVIS_BUILD_DIR}
fi
NAME=`python setup.py --name`
VERSION=`python setup.py -V`
pip install -r requirements.txt
# not totally sure if pyOpenSSl is needed (JIE)
pip install pyOpenSSL
python setup.py install

echo "Building URI Handler"
cd "${DEST}"
rm -rf build dist
python setup_uri_handler.py py2app

echo "Signing URI Handler"
codesign -s "${LBRY_DEVELOPER_ID}" -f "${DEST}/dist/LBRYURIHandler.app/Contents/Frameworks/Python.framework/Versions/2.7"
codesign -s "${LBRY_DEVELOPER_ID}" -f "${DEST}/dist/LBRYURIHandler.app/Contents/MacOS/python"
# not sure if --deep is appropriate here, but need to get LBRYURIHandler.app/Contents/Frameworks/libcrypto.1.0.0.dylib signed
codesign --deep -s "${LBRY_DEVELOPER_ID}" -f "${DEST}/dist/LBRYURIHandler.app/Contents/MacOS/LBRYURIHandler"
codesign -vvvv "${DEST}/dist/LBRYURIHandler.app"

pip install certifi
MODULES="pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-CFNetwork"
if [ ${ON_TRAVIS} = true ]; then
    WHEEL_DIR="${TRAVIS_BUILD_DIR}/cache/wheel"
    mkdir -p "${WHEEL_DIR}"
    # mapping from the package name to the
    # actual built wheel file is surprisingly
    # hard so instead of checking for the existance
    # of each wheel, we mark with a file when they've all been
    # built and skip when that file exists
    if [ ! -f "${WHEEL_DIR}"/finished ]; then
	pip wheel -w "${WHEEL_DIR}" ${MODULES}
	touch "${WHEEL_DIR}"/finished
    fi
    pip install "${WHEEL_DIR}"/*.whl
else
    pip install $MODULES
fi


# add lbrycrdd as a resource. Following
# http://stackoverflow.com/questions/11370012/can-executables-made-with-py2app-include-other-terminal-scripts-and-run-them
# LBRYCRDD_URL="$(curl https://api.github.com/repos/lbryio/lbrycrd/releases/latest | grep 'browser_download_url' | grep osx | cut -d'"' -f4)"
LBRYCRDD_URL="https://github.com/lbryio/lbrycrd/releases/download/v0.3.15/lbrycrd-osx.zip"
wget "${LBRYCRDD_URL}" --output-document lbrycrd-osx.zip
unzip -o lbrycrd-osx.zip
python setup_app.py py2app --resources lbrycrdd

chmod +x "${DEST}/dist/LBRY.app/Contents/Resources/lbrycrdd"

echo "Removing i386 libraries"

remove_arch () {
    if [[ `lipo "$2" -verify_arch "$1"` ]]; then
       lipo -output build/lipo.tmp -remove "$1" "$2" && mv build/lipo.tmp "$2"
    fi
}

for i in `find dist/LBRY.app/Contents/Resources/lib/python2.7/lib-dynload/ -name "*.so"`; do
    remove_arch i386 $i
done


echo "Moving LBRYURIHandler.app into LBRY.app"
mv "${DEST}/dist/LBRYURIHandler.app" "${DEST}/dist/LBRY.app/Contents/Resources"

echo "Signing LBRY.app"
codesign -s "${LBRY_DEVELOPER_ID}" -f "${DEST}/dist/LBRY.app/Contents/Frameworks/Python.framework/Versions/2.7"
codesign -s "${LBRY_DEVELOPER_ID}" -f "${DEST}/dist/LBRY.app/Contents/Frameworks/libgmp.10.dylib"
codesign -s "${LBRY_DEVELOPER_ID}" -f "${DEST}/dist/LBRY.app/Contents/MacOS/python"
# adding deep here as well because of subcomponent issues
codesign --deep -s "${LBRY_DEVELOPER_ID}" -f "${DEST}/dist/LBRY.app/Contents/MacOS/LBRY"
codesign -vvvv "${DEST}/dist/LBRY.app"

rm -rf $tmp
mv dist/LBRY.app LBRY.app
rm -rf dist "${NAME}.${VERSION}.dmg"
dmgbuild -s dmg_settings.py "LBRY" "${NAME}.${VERSION}.dmg"
