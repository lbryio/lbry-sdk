set -x
# must also be updated in travis.yml
TORBA_VERSION=v0.5.4a2
rm -rf /tmp/.wine-*

apt-get -qq update
apt-get -qq install -y git

pip install setuptools_scm

cd lbry

# Download from their CI until its not released. Remove later!
wget -Onetifaces-0.10.7-cp37-cp37m-win32.whl https://ci.appveyor.com/api/buildjobs/6hworunifsymrhp2/artifacts/dist%2Fnetifaces-0.10.7-cp37-cp37m-win32.whl
pip install netifaces-0.10.7-cp37-cp37m-win32.whl

git clone --depth=1 --single-branch --branch ${TORBA_VERSION} https://github.com/lbryio/torba.git
cd torba
pip install .
cd ..
rm -rf torba

pip show torba
pip install -e .
pip install pywin32

pyinstaller --additional-hooks-dir=scripts/. --icon=icons/lbry256.ico -F -n lbrynet lbrynet/extras/cli.py
wine dist/lbrynet.exe --version
