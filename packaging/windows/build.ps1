
Set-PSDebug -Trace 1

# this is a port of setup_qa.sh used for the unix platforms
If (${Env:APPVEYOR_REPO_TAG} -NotMatch "true") {
   C:\Python27\python.exe packaging\append_sha_to_version.py lbrynet\__init__.py ${Env:APPVEYOR_REPO_COMMIT}

   wget https://s3.amazonaws.com/lbry-ui/development/dist.zip -OutFile dist.zip
   Expand-Archive dist.zip -dest lbrynet\resources\ui
   wget https://s3.amazonaws.com/lbry-ui/development/data.json -OutFile lbrynet\resources\ui\data.json
}

C:\Python27\python.exe setup.py build bdist_msi
signtool.exe sign /f packaging\windows\certs\lbry2.pfx /p %key_pass% /tr http://tsa.starfieldtech.com /td SHA256 /fd SHA256 dist\*.msi
