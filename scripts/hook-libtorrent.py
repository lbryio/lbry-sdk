"""
Hook for libtorrent.
"""

import os
import glob
import os.path
from PyInstaller.utils.hooks import get_module_file_attribute
from PyInstaller import compat


def get_binaries():
    if compat.is_win:
        files = ('c:/Windows/System32/libssl-1_1-x64.dll', 'c:/Windows/System32/libcrypto-1_1-x64.dll')
        for file in files:
            if not os.path.isfile(file):
                print(f"MISSING {file}")
        return [(file, '.') for file in files]
    return []


binaries = get_binaries()
for file in glob.glob(os.path.join(get_module_file_attribute('libtorrent'), 'libtorrent*pyd*')):
    binaries.append((file, 'libtorrent'))
