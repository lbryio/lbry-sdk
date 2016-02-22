#!/bin/sh

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

if ! brew list berkeley-db4 &>/dev/null; then
    echo "Installing berkeley-db4"
    sudo -u ${SUDO_USER} brew install https://rawgit.com/jackrobison/homebrew/master/Library/Formula/berkeley-db4.rb &>/dev/null
    sudo -u ${SUDO_USER} brew link --force berkeley-db4 &>/dev/null
else
    echo "berkeley-db4 already installed"
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