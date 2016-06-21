#!/bin/bash

set -o errexit
set -o xtrace

DEST=`pwd`
tmp="${DEST}/build"

rm -rf build dist LBRY.app

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
    cd ${TRAVIS_BUILD_DIR}
    LBRY=${TRAVIS_BUILD_DIR}
fi
NAME=`python setup.py --name`
VERSION=`python setup.py -V`
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

pip install certifi pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-CFNetwork
python setup_app.py py2app

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
rm -rf dist
hdiutil create "${NAME}.${VERSION}.dmg" -volname lbry -srcfolder LBRY.app
