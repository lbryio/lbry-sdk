#!/bin/sh

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

if ! brew list openssl &>/dev/null; then
	echo "Installing openssl..."
	sudo -u ${SUDO_USER} brew install openssl &>/dev/null
	sudo -u ${SUDO_USER} brew link --force openssl &>/dev/null
else
    echo "openssl already installed..."
fi

if ! which pip &>/dev/null; then
	echo "Installing pip..."
	sudo easy_install pip &>/dev/null
else
	echo "pip already installed"
fi

if ! python -c 'import gmpy' &>/dev/null; then
	echo "Installing gmpy..."
	sudo pip install gmpy &>/dev/null
else
	echo "gmpy already installed..."
fi

if ! python -c 'import service_identity' &>/dev/null; then
	echo "Installing service_identity..."
	sudo pip install service_identity &>/dev/null
else
	echo "gmpy already installed..."
fi

if ! python -c 'import rumps' &>/dev/null; then
	echo "Installing rumps..."
	sudo pip install rumps &>/dev/null
else
	echo "rumps already installed..."
fi

lbrycrd_directory="/Users/${SUDO_USER}/Library/Application Support/lbrycrd"

current_version=$(git ls-remote https://github.com/jackrobison/lbrynet-app.git | grep HEAD | cut -f 1)

if [ -d "$lbrycrd_directory" ]; then
	if [ -f "${lbrycrd_directory}/lbry_app_version.txt" ]; then
		if grep -Fxq "$current_version" "${lbrycrd_directory}/lbry_app_version.txt"; then
			echo "LBRY version $current_version is up to date"
			exit
		fi
	fi
fi

tmp=$(mktemp -d)
cd $tmp

echo "Downloading LBRY update"
git clone --depth 1 https://github.com/jackrobison/lbrynet-app.git &>/dev/null
cd lbrynet-app
unzip LBRY.app.zip &>/dev/null
unzip LBRYURIHandler.app.zip &>/dev/null
unzip LBRY\ Updater.app.zip &>/dev/null

echo "Installing update"

mkdir -p "$lbrycrd_directory"
echo $current_version > "${lbrycrd_directory}/lbry_app_version.txt"

rm -rf /Applications/LBRY.app &>/dev/null
rm -rf /Applications/LBRYURIHandler.app &>/dev/null
rm -rf /Applications/LBRY\ Updater.app &>/dev/null

mv -f LBRY.app /Applications
mv -f LBRYURIHandler.app /Applications
mv -f LBRY\ Updater.app /Applications

echo "Cleaning up"

cd ../../
rm -rf $tmp