#!/bin/sh

if [ "$EUID" -ne 0 ]
  then echo "Please run as sudo"
  exit
fi

echo "**********************************"
echo "Installing LBRY and dependencies"
echo "**********************************"

if ! xcode-select -p &>/dev/null; then
	echo
	echo "You need to install xcode command line tools to install lbry."
	echo "A popup to do so should appear, once you're done the installer will resume"
	echo
	xcode-select --install &>/dev/null
	while ! xcode-select -p &>/dev/null; do
		sleep 1
    done
    echo "Installed xcode command line tools"
else
	echo "Xcode command line tools already installed..."
fi

if ! which brew &>/dev/null; then
	echo "Installing brew..."
	sudo -u ${SUDO_USER} ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"  < /dev/null  &>/dev/null
else
	echo "Updating brew..."
	sudo -u ${SUDO_USER} brew update &>/dev/null
fi

if ! brew list mpfr &>/dev/null; then
	echo "Installing mpfr..."
	sudo -u ${SUDO_USER} brew install mpfr &>/dev/null
else
	echo "mpfr already installed..."
fi

if ! brew list libmpc &>/dev/null; then
	echo "Installing libmpc..."
	sudo -u ${SUDO_USER} brew install libmpc &>/dev/null
else
	echo "libmpc already installed..."
fi

if ! which pip &>/dev/null; then
	echo "Installing pip..."
	sudo easy_install pip &>/dev/null
else
	echo "pip already installed"
fi

echo "Cloning and installing lbryum..."
git clone --depth 1 https://github.com/lbryio/lbryum.git &>/dev/null
cd lbryum
sudo python setup.py install &>/dev/null
cd ..
rm -rf lbryum &>/dev/null

echo "Cloning and installing lbry..."
git clone --depth 1 https://github.com/lbryio/lbry.git &>/dev/null
cd lbry
sudo python setup.py install &>/dev/null
cd ..
rm -rf lbry &>/dev/null

sudo chmod -R 755 /Library/Python/2.7/site-packages/

echo "**********************************"
echo "All done!"
echo "**********************************"
echo " "
echo "run 'lbrynet-daemon' to start lbry"