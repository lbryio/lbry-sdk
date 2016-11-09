C:\Python27\python.exe setup.py install

# If this is a build because of a tag, make sure that
# its either a testing tag or a tag that matches the version
# specified in the source code.
If (${Env:APPVEYOR_REPO_TAG} -Match "true") {
   If (${Env:APPVEYOR_REPO_TAG_NAME} -Like "test*") {
      exit 0
   }
   # non-testing tags should be in the form v1.2.3
   If ("v$(C:\Python27\python.exe setup.py -V)" -Match ${Env:APPVEYOR_REPO_TAG_NAME}) {
      exit 0
   }
   exit 1
}