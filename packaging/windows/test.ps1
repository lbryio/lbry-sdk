C:\Python27\Scripts\pip.exe install mock
C:\Python27\Scripts\pip.exe install pylint
C:\Python27\python.exe C:\Python27\Scripts\trial.py C:\projects\lbry\tests\unit
if ($LastExitCode -ne 0) { $host.SetShouldExit($LastExitCode)  }
C:\Python27\Scripts\pylint.exe -E --disable=inherit-non-class --disable=no-member --ignored-modules=distutils --enable=unused-import --enable=bad-whitespace lbrynet packaging/windows/lbry-win32-app/LBRYWin32App.py
if ($LastExitCode -ne 0) { $host.SetShouldExit($LastExitCode)  }
