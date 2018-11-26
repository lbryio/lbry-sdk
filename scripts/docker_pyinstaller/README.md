# PyInstaller docker image fork used on build process

This is a temporary fork of [docker-pyinstaller](https://github.com/cdrx/docker-pyinstaller/tree/master/win32/py3) that uses [zzhiyi's fork of wine](https://github.com/zzhiyi/wine/tree/kernelbase/PathCchCanonicalizeEx) to build with Python 3.7.1 and PyInstaller 3.4.
Once those changes settles both in wine and docker-pyinstaller repo, this folder should be removed.

## But hey, where is `wine_3.20.1-1_i386.deb` and how was it generated?
It's a package generated out of above mentioned wine branch. You can find instructions on how to generate Debian packages on the [Wine Wiki](https://wiki.winehq.org/Building_Biarch_Wine_On_Ubuntu) or use a helper like [docker-wine-builder](https://github.com/shyba/docker-wine-builder).
