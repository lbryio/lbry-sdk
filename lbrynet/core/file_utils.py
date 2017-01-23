import os
import sys
import subprocess

def start(path):
    """
    Open a file with the OS's default program. (Cross-platform equivalent of os.startfile() for
    Windows)
    """

    if not os.path.isfile(path):
        raise(IOError, "No such file: '%s'" % path)

    if sys.platform == 'darwin':
        subprocess.Popen(['open', path])
    elif os.name == 'posix':
        subprocess.Popen(['xdg-open', path])
    elif sys.platform == 'win32':
        os.startfile(path)

def reveal(path):
    """
    Reveal a file in file browser.
    """

    if not os.path.isfile(path):
        raise(IOError, "No such file: '%s'" % path)

    if sys.platform == 'darwin':
        subprocess.Popen(['open', '-R', path])
    elif os.name == 'posix':
        # No easy way to reveal specific files on Linux, so just open the containing directory
        subprocess.Popen(['xdg-open', os.path.dirname(path)])
    elif sys.platform == 'win32':
        subprocess.Popen(['explorer', '/select', path])
