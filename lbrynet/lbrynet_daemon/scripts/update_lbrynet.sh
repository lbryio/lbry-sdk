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

if ! python -c "import six; exit(0) if six.__version__ == '1.9.0' else exit(1)" &>/dev/null; then
    echo "Installing six 1.9.0 for python"
    curl -O https://pypi.python.org/packages/source/s/six/six-1.9.0.tar.gz &>/dev/null
    tar xf six-1.9.0.tar.gz &>/dev/null
    cd six-1.9.0
    sudo python setup.py install &>/dev/null
    cd ..
    rm -rf six-1.9.0
    rm six-1.9.0.tar.gz
fi

lbrynet_directory="/Users/${SUDO_USER}/Library/Application Support/lbrynet"

lbrynet_current_version=$(git ls-remote https://github.com/lbryio/lbry.git | grep HEAD | cut -f 1)

if [ -d "$lbrynet_directory" ]; then
	if [ -f "${lbrynet_directory}/lbrynet_version.txt" ]; then
		if grep -Fxq "$lbrynet_current_version" "${lbrynet_directory}/lbrynet_version.txt"; then
			echo "LBRYnet version $lbrynet_current_version is up to date"
		else
            tmp=$(mktemp -d)
            cd $tmp

            echo "Downloading LBRYnet update"

            git clone --depth 1 https://github.com/lbryio/lbry.git &>/dev/null
            cd lbry

            echo "Installing update"
            sudo python setup.py install &>/dev/null
            mkdir -p "$lbrynet_directory"
            echo $lbrynet_current_version > "${lbrynet_directory}/lbrynet_version.txt"

            echo "Cleaning up"

            cd ../../
            rm -rf $tmp
		fi
	else
        tmp=$(mktemp -d)
        cd $tmp

        echo "Downloading LBRYnet update"

        git clone --depth 1 https://github.com/lbryio/lbry.git &>/dev/null
        cd lbry

        echo "Installing update"
        sudo python setup.py install &>/dev/null
        mkdir -p "$lbrynet_directory"
        echo $lbrynet_current_version > "${lbrynet_directory}/lbrynet_version.txt"

        echo "Cleaning up"

        cd ../../
        rm -rf $tmp
	fi
fi

lbryum_current_version=$(git ls-remote https://github.com/lbryio/lbryum.git | grep HEAD | cut -f 1)

if [ -d "$lbrynet_directory" ]; then
	if [ -f "${lbrynet_directory}/lbryum_version.txt" ]; then
		if grep -Fxq "$lbryum_current_version" "${lbrynet_directory}/lbryum_version.txt"; then
			echo "LBRYum version $lbryum_current_version is up to date"
		else
            tmp=$(mktemp -d)
            cd $tmp

            echo "Downloading LBRYum update"

            git clone --depth 1 https://github.com/lbryio/lbryum.git &>/dev/null
            cd lbryum

            echo "Installing update"
            sudo python setup.py install &>/dev/null
            mkdir -p "$lbrynet_directory"
            echo $lbryum_current_version > "${lbrynet_directory}/lbryum_version.txt"

            echo "Cleaning up"

            cd ../../
            rm -rf $tmp
		fi
	else
        tmp=$(mktemp -d)
        cd $tmp

        echo "Downloading LBRYum update"

        git clone --depth 1 https://github.com/lbryio/lbryum.git &>/dev/null
        cd lbryum

        echo "Installing update"
        sudo python setup.py install &>/dev/null
        mkdir -p "$lbrynet_directory"
        echo $lbryum_current_version > "${lbrynet_directory}/lbryum_version.txt"

        echo "Cleaning up"

        cd ../../
        rm -rf $tmp
	fi
fi