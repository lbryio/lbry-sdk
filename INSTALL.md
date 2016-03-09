#### Installing lbrynet on Linux
--------------------------

The following packages are necessary (the following are their names on Ubuntu):
libgmp3-dev build-essential python2.7 python2.7-dev python-pip

To install them on Ubuntu:
sudo apt-get install libgmp3-dev build-essential python2.7 python2.7-dev python-pip

python setup.py build bdist_egg
sudo python setup.py install
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
