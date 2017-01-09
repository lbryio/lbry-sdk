# Installing LBRY

The recommended way to install LBRY is to use an installer. We provide installers for all major operating systems. See the [README](README).

These instructions are for installing from source code, which is recommended if you are interested in doing development work or LBRY is not available on your operating system (good luck, TempleOS users).

## Prerequisites

Before starting, you'll need to install some additional libraries depending on your operating system.

### OS X Prerequisites

Install [xcode command line tools](https://developer.xamarin.com/guides/testcloud/calabash/configuring/osx/install-xcode-command-line-tools/) and [homebrew](http://brew.sh/).

Remaining dependencies can then be installed by running:

```
brew install mpfr libmpc
sudo easy_install pip
sudo pip install virtualenv
```

### Linux Prerequisites

On Ubuntu (we recommend 16.04), install the following:

```
sudo apt-get install libgmp3-dev build-essential python2.7 python2.7-dev \
     python-pip git python-virtualenv libssl-dev libffi-dev
```

If you're running another Linux flavor, install the equivalent of the above packages for your system.

### Windows Prerequisites

Install [mingw32](http://www.mingw.org/) base and c++ compiler.

Add C:\MinGW\bin to the windows PATH.

Enable distutils to compile with mingw32 by creating a distutils.cfg file in *PYTHONPATH\Lib\distutils* containing:

```
[build]
compiler = mingw32
```

If using virtualenv, which is recommended, copy the *PYTHONPATH\Lib\distutils* directory to the virtualenv.

It's recommended to use [Unofficial Windows Binaries for Python Extension Packages](http://www.lfd.uci.edu/~gohlke/pythonlibs/) for as many of the required packages as possible.
Currently, available binaries include:
- Cython
- Twisted
- Zope.interface
- pywin32
- Yapsy
- cx_Freeze
- requests
- gmpy

Install the each of the preceding binaries with `pip install *.whl`

Install pywin32 system files by run `python.exe Scripts\pywin32_postinstall.py -install` from an elevated command prompt.

Finally, you'll need [miniupnpc](https://pypi.python.org/pypi/miniupnpc/1.9). Download the source and compile with MinGW by running `mingw32make.bat`.
Then, install the module by running `python setupmingw32.py install`.

## Installation

We strongly recommend creating a new virtualenv for LBRY:

 ```
 virtualenv lbry-venv
 source lbry-venv/bin/activate
 ```

Then, install the package in the new virtualenv:
 
 ```
 git clone https://github.com/lbryio/lbry.git
 cd lbry
 pip install -r requirements.txt
 pip install .
 ```

To start LBRY, run `lbrynet-daemon` in a terminal.
