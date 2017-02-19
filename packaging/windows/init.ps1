$env:Path += ";C:\MinGW\bin\"

$env:Path += ";C:\Program Files (x86)\Windows Kits\10\bin\x86\"

gcc --version

mingw32-make --version

mkdir C:\temp

Invoke-WebRequest "https://pypi.python.org/packages/55/90/e987e28ed29b571f315afea7d317b6bf4a551e37386b344190cffec60e72/miniupnpc-1.9.tar.gz" -OutFile "C:\temp\miniupnpc-1.9.tar.gz"

cd C:\temp

7z e miniupnpc-1.9.tar.gz

7z x miniupnpc-1.9.tar

cd C:\temp\miniupnpc-1.9

mingw32-make.exe -f Makefile.mingw

C:\Python27\python.exe C:\temp\miniupnpc-1.9\setupmingw32.py build --compiler=mingw32

C:\Python27\python.exe C:\temp\miniupnpc-1.9\setupmingw32.py install

Invoke-WebRequest "https://github.com/lbryio/lbry/raw/master/packaging/windows/libs/gmpy-1.17-cp27-none-win32.whl" -OutFile "C:\temp\gmpy-1.17-cp27-none-win32.whl"

C:\Python27\Scripts\pip.exe install "C:\temp\gmpy-1.17-cp27-none-win32.whl"

C:\Python27\Scripts\pip.exe install pypiwin32==219

C:\Python27\Scripts\pip.exe install six==1.9.0

C:\Python27\Scripts\pip.exe install requests==2.9.1

C:\Python27\Scripts\pip.exe install zope.interface==4.3.3

# this is a patched to allow version numbers with non-integer values
# and it is branched off of 4.3.3
C:\Python27\Scripts\pip.exe install https://bitbucket.org/jobevers/cx_freeze/get/handle-version.tar.gz

C:\Python27\Scripts\pip.exe install cython==0.24.1

C:\Python27\Scripts\pip.exe install Twisted==16.6.0

C:\Python27\Scripts\pip.exe install Yapsy==1.11.223

C:\Python27\Scripts\pip.exe install appdirs==1.4.0

C:\Python27\Scripts\pip.exe install argparse==1.2.1

C:\Python27\Scripts\pip.exe install colorama==0.3.7

C:\Python27\Scripts\pip.exe install dnspython==1.12.0

C:\Python27\Scripts\pip.exe install ecdsa==0.13
C:\Python27\Scripts\pip.exe install envparse==0.2.0

C:\Python27\Scripts\pip.exe install jsonrpc==1.2

C:\Python27\Scripts\pip.exe install jsonrpclib==0.1.7

C:\Python27\Scripts\pip.exe install loggly-python-handler==1.0.0

C:\Python27\Scripts\pip.exe install pbkdf2==1.3

C:\Python27\Scripts\pip.exe install protobuf==3.0.0

C:\Python27\Scripts\pip.exe install pycrypto==2.6.1

C:\Python27\Scripts\pip.exe install python-bitcoinrpc==0.1

C:\Python27\Scripts\pip.exe install pyyaml==3.12

C:\Python27\Scripts\pip.exe install qrcode==5.2.2

C:\Python27\Scripts\pip.exe install requests_futures==0.9.7

C:\Python27\Scripts\pip.exe install seccure==0.3.1.3

C:\Python27\Scripts\pip.exe install simplejson==3.8.2

C:\Python27\Scripts\pip.exe install slowaes==0.1a1

C:\Python27\Scripts\pip.exe install txJSON-RPC==0.5

C:\Python27\Scripts\pip.exe install unqlite==0.5.3

C:\Python27\Scripts\pip.exe install wsgiref==0.1.2

C:\Python27\Scripts\pip.exe install base58==0.2.2

C:\Python27\Scripts\pip.exe install googlefinance==0.7

C:\Python27\Scripts\pip.exe install jsonschema==2.5.1

C:\Python27\Scripts\pip.exe install git+https://github.com/lbryio/lbryum.git

cd C:\projects\lbry
