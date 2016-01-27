Prerequisites
-------------

To use the LBRYWallet, which enables spending and accepting LBRYcrds in exchange for data, the
LBRYcrd application (insert link to LBRYcrd website here) must be installed and running. If
this is not desired, the testing client can be used to simulate trading points, which is
built into LBRYnet.

on Ubuntu:

```
sudo apt-get install libgmp3-dev build-essential python-dev python-pip
```

Getting the source
------------------

Don't you already have it?

Setting up the environment
--------------------------

It's recommended that you use a virtualenv

```
sudo apt-get install python-virtualenv
cd <source base directory>
virtualenv .
source bin/activate
```

(to deactivate the virtualenv, enter 'deactivate')

```
python setup.py install
```

this will install all of the libraries and a few applications

For running the file sharing application, see [RUNNING](RUNNING.md)

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
