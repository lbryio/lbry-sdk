set -x
rm -rf /tmp/.wine-*

apt-get -qq update
apt-get -qq install -y git

pip install setuptools_scm

# Download from their CI until its not released. Remove later!
wget -Onetifaces-0.10.7-cp37-cp37m-win32.whl https://ci.appveyor.com/api/buildjobs/6hworunifsymrhp2/artifacts/dist%2Fnetifaces-0.10.7-cp37-cp37m-win32.whl
pip install netifaces-0.10.7-cp37-cp37m-win32.whl

cd lbry
cd torba
pip install .
cd ..
cd lbry
pip install -e .
pip install pywin32

pyinstaller --additional-hooks-dir=scripts/. --icon=icons/lbry256.ico -F -n lbrynet lbrynet/extras/cli.py
wine dist/lbrynet.exe --version
