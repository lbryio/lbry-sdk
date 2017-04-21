$env:Path += ";C:\MinGW\bin\"

$env:Path += ";C:\Program Files (x86)\Windows Kits\10\bin\x86\"
gcc --version
mingw32-make --version

# build/install miniupnpc manually
tar zxf miniupnpc-1.9.tar.gz
cd miniupnpc-1.9
mingw32-make -f Makefile.mingw
python setupmingw32.py build --compiler=mingw32
python setupmingw32.py install
cd ..\
Remove-Item -Recurse -Force miniupnpc-1.9

# copy requirements from lbry, but remove gmpy and miniupnpc (installed manually)
Get-Content ..\requirements.txt | Select-String -Pattern 'gmpy|miniupnpc' -NotMatch | Out-File requirements_base.txt
# add in gmpy wheel
Add-Content requirements.txt "./gmpy-1.17-cp27-none-win32.whl"

pip install -r requirements.txt

python set_build.py

pyinstaller -y daemon.onefile.spec
pyinstaller -y cli.onefile.spec

python zip_daemon.py
python release_on_tag.py