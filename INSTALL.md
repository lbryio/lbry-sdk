#### Installing the LBRY app
--------------------------

Installing LBRY is simple. You can get a dmg installer for OS X (Mavericks and up) or a .deb for linux [here](https://lbry.io/get). 

##### OS X
Just drag and drop LBRY.app into your applications folder (replacing any older versions). When it's running you'll have a LBRY icon in your status bar.

##### Linux
Double click the .deb file and follow the prompts. The app can be started by searching "LBRY", and it can be turned off by clicking the red 'x' in the browser interface.

On both systems you can also open the UI while the app is running by going to lbry://lbry in Firefox or Safari, or localhost:5279 in Chrome.


#### Installing LBRY command line

##### OS X
You can install LBRY command line by running `curl -sL https://rawgit.com/lbryio/lbry-setup/master/lbry_setup_osx.sh | sudo bash` in a terminal. This script will install lbrynet and its dependancies, as well as the app. You can start LBRY by either starting the app or by running `lbrynet-daemon` from a terminal. 

##### Linux
On Ubuntu or Mint you can install the prerequisites and lbrynet by running
 
 ```
 sudo apt-get install libgmp3-dev build-essential python2.7 python2.7-dev python-pip
 git clone https://github.com/lbryio/lbry.git
 cd lbry
 sudo python setup.py install
 ```

To start LBRY, run `lbrynet-daemon` in a terminal.

#### On windows:

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
