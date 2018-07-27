set -x

rm -rf /tmp/.wine-*

apt-get -qq update
apt-get -qq install -y git

git clone https://github.com/lbryio/lbryschema.git --depth 1
git clone https://github.com/lbryio/torba.git --depth 1
git clone https://github.com/twisted/twisted.git --depth 1 --branch twisted-18.7.0
sed -i -e '172,184{s/^/#/}' twisted/src/twisted/python/_setup.py

pip install setuptools_scm
cd twisted && pip install -e .[tls] && cd ..
cd lbryschema && pip install -e . && cd ..
cd torba && pip install -e . && cd ..

cd lbry
pip install -e .
pyinstaller -F -n lbrynet lbrynet/cli.py
wine dist/lbrynet.exe --version
