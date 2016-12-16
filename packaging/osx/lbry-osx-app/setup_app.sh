#!/bin/bash

set -o errexit
set -o xtrace

DEST=`pwd`
tmp="${DEST}/build"
ON_TRAVIS=false

rm -rf build dist LBRY.app

echo "Updating lbrynet"
if [ -z ${TRAVIS_BUILD_DIR+x} ]; then
    # building locally
    mkdir -p $tmp
    cd $tmp
    git clone --depth 1 http://github.com/lbryio/lbry.git
    cd lbry
    LBRY="${tmp}/lbry"
else
    # building on travis
    ON_TRAVIS=true
    cd ${TRAVIS_BUILD_DIR}
    LBRY=${TRAVIS_BUILD_DIR}
fi

pip install wheel
MODULES="pyobjc-core==3.1.1 pyobjc-framework-Cocoa==3.1.1 pyobjc-framework-CFNetwork==3.1.1 pyobjc-framework-Quartz==3.1.1"
if [ ${ON_TRAVIS} = true ]; then
    WHEEL_DIR="${TRAVIS_BUILD_DIR}/cache/wheel"
    mkdir -p "${WHEEL_DIR}"
    # mapping from the package name to the
    # actual built wheel file is surprisingly
    # hard so instead of checking for the existance
    # of each wheel, we mark with a file when they've all been
    # built and skip when that file exists
    for MODULE in ${MODULES}; do
	if [ ! -f "${WHEEL_DIR}"/${MODULE}.finished ]; then
	    pip wheel -w "${WHEEL_DIR}" ${MODULE}
	    touch "${WHEEL_DIR}"/${MODULE}.finished
	    pip install ${MODULE}
	fi
    done
fi
pip install $MODULES


pip install dmgbuild==1.1.0
export PATH=${PATH}:/Library/Frameworks/Python.framework/Versions/2.7/bin

# pyopenssl is needed because OSX ships an old version of openssl by default
# and python will use it without pyopenssl
pip install PyOpenSSL jsonrpc certifi

NAME=`python setup.py --name`
VERSION=`python setup.py -V`
pip install -r requirements.txt

pip install pylint
pylint -E --disable=inherit-non-class --disable=no-member --ignored-modules=distutils \
       --enable=unused-import --enable=bad-whitespace lbrynet packaging/osx/lbry-osx-app/lbrygui/

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

# py2app will skip _cffi_backend without explicitly including it
# and without this, we will get SSL handshake errors when connecting
# to bittrex
python setup_app.py py2app -i _cffi_backend

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
