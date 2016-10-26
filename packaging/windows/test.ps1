C:\Python27\Scripts\pip.exe install mock
C:\Python27\Scripts\pip.exe install pylint
C:\Python27\python.exe C:\Python27\Scripts\trial.py C:\projects\lbry\tests\unit
if ($LastExitCode -ne 0) { $host.SetShouldExit($LastExitCode)  }
