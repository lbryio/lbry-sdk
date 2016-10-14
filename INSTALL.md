#### Installing the LBRY app
--------------------------

Installing LBRY is simple. You can get a dmg installer for OS X or a .deb for linux [here](https://github.com/lbryio/lbry/releases/latest). 

##### OS X
Drag and drop LBRY.app into your applications folder (replacing any older versions). When it's running you'll have a LBRY icon in your status bar and the browser will open to the UI.

##### Linux
Double click the .deb file and follow the prompts. The app can be started by searching "LBRY", and it can be turned off by clicking the red 'x' in the browser interface.

On both systems you can also open the UI while the app is running by going to lbry://lbry in Firefox or Safari, or localhost:5279 in Chrome.


#### Installing LBRY from source
--------------------------

Installing LBRY from source is not the recommended way to install
LBRY. Only do so if you're interested in doing development work.

##### OS X Prerequisites

In order to install LBRY from source you'll need to first install [xcode command line tools](https://developer.xamarin.com/guides/testcloud/calabash/configuring/osx/install-xcode-command-line-tools/) and [homebrew](http://brew.sh/). The dependencies can then be installed by running

```
brew install mpfr libmpc
sudo easy_install pip
sudo pip install virtualenv
```

##### Linux Prerequisites
On Ubuntu or Mint you can install the prerequisites by running

 ```
 sudo apt-get install libgmp3-dev build-essential python2.7 python2.7-dev \
     python-pip git python-virtualenv
 ```

##### OSX and Linux Installation

It is strongly recommended to create a new virtualenv for LBRY

 ```
 virtualenv lbry-venv
 source lbry-venv/bin/activate
 ```

and install the package in the new virtualenv:
 
 ```
 git clone https://github.com/lbryio/lbry.git
 cd lbry
 python setup.py install
 ```

To start LBRY, run `lbrynet-daemon` in a terminal.


##### On windows

Install [mingw32](http://www.mingw.org/) base and c++ compiler.

Add C:\MinGW\bin to the windows PATH.

Enable distutils to compile with mingw32 by creating a distutils.cfg file in *PYTHONPATH\Lib\distutils* containing
```
[build]
compiler = mingw32
```

If using virtualenv, copy the *PYTHONPATH\Lib\distutils* directory to the virtualenv.

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

Install the rest of the required modules with the standard `pip install module` command

The one module which requires additional work is [miniupnpc](https://pypi.python.org/pypi/miniupnpc/1.9).
Download the source and compile with MinGW by running `mingw32make.bat`
Then install the module by running `python setupmingw32.py install`
