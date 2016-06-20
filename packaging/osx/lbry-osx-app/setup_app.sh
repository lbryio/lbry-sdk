#!/bin/bash

set -o errexit
set -o xtrace

dest=`pwd`
tmp="${dest}/build"

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
python setup.py install
echo "Building URI Handler"
rm -rf build dist
python setup_uri_handler.py py2app

echo "Signing URI Handler"
codesign -s "${LBRY_DEVELOPER_ID}" -f "${LBRY}/dist/LBRYURIHandler.app/Contents/Frameworks/Python.framework/Versions/2.7"
codesign -s "${LBRY_DEVELOPER_ID}" -f "${LBRY}/dist/LBRYURIHandler.app/Contents/MacOS/python"
codesign -s "${LBRY_DEVELOPER_ID}" -f "${LBRY}/dist/LBRYURIHandler.app/Contents/MacOS/LBRYURIHandler"
codesign -vvvv "${LBRY}/dist/LBRYURIHandler.app"

cd $dest
python setup.py py2app &>/dev/null

echo "Moving in correct libgmp"
rm "${dest}/dist/LBRY.app/Contents/Frameworks/libgmp.10.dylib"
cp "${dest}/libgmp.10.dylib" "${dest}/dist/LBRY.app/Contents/Frameworks"

echo "Removing i386 libraries"

remove_arch () {
    lipo -output build/lipo.tmp -remove "$1" "$2" && mv build/lipo.tmp "$2"
}
for i in dist/LBRY.app/Contents/Resources/lib/python2.7/lib-dynload/* ; do
    remove_arch i386 ${i}
done

echo "Moving LBRYURIHandler.app into LBRY.app"
mv "${LBRY}/dist/LBRYURIHandler.app" "${dest}/dist/LBRY.app/Contents/Resources"

echo "Signing LBRY.app"
codesign -s "${LBRY_DEVELOPER_ID}" -f "${dest}/dist/LBRY.app/Contents/Frameworks/Python.framework/Versions/2.7"
codesign -s "${LBRY_DEVELOPER_ID}" -f "${dest}/dist/LBRY.app/Contents/Frameworks/libgmp.10.dylib"
codesign -s "${LBRY_DEVELOPER_ID}" -f "${dest}/dist/LBRY.app/Contents/MacOS/python"
codesign -s "${LBRY_DEVELOPER_ID}" -f "${dest}/dist/LBRY.app/Contents/MacOS/LBRY"
codesign -vvvv "${dest}/dist/LBRY.app"

rm -rf $tmp
mv dist/LBRY.app LBRY.app
rm -rf dist
