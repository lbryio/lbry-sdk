dest=`pwd`
tmp="${dest}/build"
id=`cat id.conf`

rm -rf build dist LBRY.app

mkdir -p $tmp
cd $tmp

echo "Updating lbryum"
git clone --depth 1 http://github.com/lbryio/lbryum.git
cd lbryum
python setup.py install &>/dev/null
cd ..
echo "Updating lbrynet"
git clone --depth 1 -b development http://github.com/lbryio/lbry.git
cd lbry
python setup.py install &>/dev/null

cd $dest
echo "Building URI Handler"
python setup_uri_handler.py py2app &>/dev/null

echo "Signing URI Handler"
codesign -s "Developer ID Application: LBRY Inc (${id})" -f "dist/LBRYURIHandler.app/Contents/Frameworks/Python.framework/Versions/2.7"
codesign -s "Developer ID Application: LBRY Inc (${id})" -f "dist/LBRYURIHandler.app/Contents/MacOS/python"
codesign -s "Developer ID Application: LBRY Inc (${id})" -f "dist/LBRYURIHandler.app/Contents/MacOS/LBRYURIHandler"
codesign -vvvv "dist/LBRYURIHandler.app"
mv "dist/LBRYURIHandler.app" "LBRYURIHandler.app"
rm -rf build dist

echo "Building app"
python setup_app.py py2app &>/dev/null

echo "Moving in correct libgmp"
rm "${dest}/dist/LBRY.app/Contents/Frameworks/libgmp.10.dylib"
cp "${dest}/libgmp.10.dylib" "${dest}/dist/LBRY.app/Contents/Frameworks"

echo "Removing i386 libraries"

remove_arch () {
    lipo -output build/lipo.tmp -remove "$1" "$2" && mv build/lipo.tmp "$2"
}
for i in dist/LBRY.app/Contents/Resources/lib/python2.7/lib-dynload/* ; do
    #remove_arch ppc ${i}
    remove_arch i386 ${i}
done

echo "Moving LBRYURIHandler.app into LBRY.app"
mv "${dest}/LBRYURIHandler.app" "${dest}/dist/LBRY.app/Contents/Resources"

echo "Signing LBRY.app"
codesign -s "Developer ID Application: LBRY Inc (${id})" -f "${dest}/dist/LBRY.app/Contents/Frameworks/Python.framework/Versions/2.7"
codesign -s "Developer ID Application: LBRY Inc (${id})" -f "${dest}/dist/LBRY.app/Contents/Frameworks/libgmp.10.dylib"
codesign -s "Developer ID Application: LBRY Inc (${id})" -f "${dest}/dist/LBRY.app/Contents/MacOS/python"
codesign -s "Developer ID Application: LBRY Inc (${id})" -f "${dest}/dist/LBRY.app/Contents/MacOS/LBRY"
codesign -vvvv "${dest}/dist/LBRY.app"

rm -rf $tmp
mv dist/LBRY.app LBRY.app
rm -rf dist

chown -R ${SUDO_USER} LBRY.app