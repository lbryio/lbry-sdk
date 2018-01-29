$env:Path += ";C:\MinGW\bin\"

$env:Path += ";C:\Program Files (x86)\Windows Kits\10\bin\x86\"
gcc --version
mingw32-make --version

# build/install miniupnpc manually
tar zxf miniupnpc-2.0.2.tar.gz
cd miniupnpc-2.0.2
mingw32-make -f Makefile.mingw
python setupmingw32.py build --compiler=mingw32
python setupmingw32.py install
cd ..\
Remove-Item -Recurse -Force miniupnpc-2.0.2

# copy requirements from lbry, but remove miniupnpc (installed manually)
Get-Content ..\requirements.txt | Select-String -Pattern 'miniupnpc' -NotMatch | Out-File requirements_base.txt

python set_build.py

pip install -r requirements.txt
pip install ..\.

pyinstaller -y daemon.onefile.spec
pyinstaller -y cli.onefile.spec
pyinstaller -y console.onefile.spec

nuget install secure-file -ExcludeVersion
secure-file\tools\secure-file -decrypt .\lbry2.pfx.enc -secret "$env:pfx_key"
signtool.exe sign /f .\lbry2.pfx /p "$env:key_pass" /tr http://tsa.starfieldtech.com /td SHA256 /fd SHA256 dist\*.exe

python zip_daemon.py
python upload_assets.py
