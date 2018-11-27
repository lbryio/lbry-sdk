set -x

rm -rf /tmp/.wine-*

apt-get -qq update
apt-get -qq install -y git

git clone https://github.com/lbryio/torba.git --depth 1
sed -i -e "s/'plyvel',//" torba/setup.py
git clone https://github.com/twisted/twisted.git --depth 1 --branch twisted-18.7.0
sed -i -e '172,184{s/^/#/}' twisted/src/twisted/python/_setup.py

pip install setuptools_scm
cd twisted && pip install -e .[tls] && cd ..
cd torba && pip install -e . && cd ..

cd lbry
python scripts/set_build.py

# Download from their CI until its not released. Remove later!
wget -Onetifaces-0.10.7-cp37-cp37m-win32.whl https://ci.appveyor.com/api/buildjobs/6hworunifsymrhp2/artifacts/dist%2Fnetifaces-0.10.7-cp37-cp37m-win32.whl
pip install netifaces-0.10.7-cp37-cp37m-win32.whl

pip install -e .

# Twisted needs that, but installing before lbry makes everything hang
# PyInstaller removed that as a dependency in 3.4
# The source file from Twisted that requires it is "src/twisted/internet/stdio.py"
pip install pywin32

pyinstaller --additional-hooks-dir=scripts/. -F -n lbrynet lbrynet/extras/cli.py
wine dist/lbrynet.exe --version
