# this is a port of setup_qa.sh used for the unix platforms
If (${Env:APPVEYOR_REPO_TAG} -NotMatch "true") {
   C:\Python27\python.exe packaging\append_sha_to_version.py lbrynet\__init__.py ${Env:APPVEYOR_REPO_COMMIT}
   if ($LastExitCode -ne 0) { $host.SetShouldExit($LastExitCode) }
   wget https://s3.amazonaws.com/lbry-ui/development/dist.zip -OutFile dist.zip
   if ($LastExitCode -ne 0) { $host.SetShouldExit($LastExitCode)  }
   Expand-Archive dist.zip -dest lbrynet\resources\ui
   if ($LastExitCode -ne 0) { $host.SetShouldExit($LastExitCode)  }
   wget https://s3.amazonaws.com/lbry-ui/development/data.json -OutFile lbrynet\resources\ui\data.json
   if ($LastExitCode -ne 0) { $host.SetShouldExit($LastExitCode)  }
}

C:\Python27\python.exe setup.py build bdist_msi
if ($LastExitCode -ne 0) { $host.SetShouldExit($LastExitCode)  }

signtool.exe sign /f packaging\windows\certs\lbry2.pfx /p %key_pass% /tr http://tsa.starfieldtech.com /td SHA256 /fd SHA256 dist\*.msi
