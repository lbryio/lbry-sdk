import sys
import os
import re


def user_download_dir():
    r"""Return full path to the user-specific download dir.

    Typical user data directories are:
        Mac OS X:  ~/Downloads
        Unix:      ~/Downloads    # or in $XDG_DOWNLOAD_DIR, if defined
        Win 7:     C:\Users\<username>\Downloads

    For Unix, we follow the XDG spec and support $XDG_DOWNLOAD_DIR.
    That means, by default "~/Downloads".
    """
    if sys.platform == "win32":
        return os.path.normpath(_get_win_download_folder())
    elif sys.platform == "darwin":
        return os.path.expanduser('~/Downloads')
    else:
        try:
            config_dirs = os.path.join(user_config_dir(), 'user-dirs.dirs')
            with open(config_dirs) as dirs_file:
                path_match = re.search(r'XDG_DOWNLOAD_DIR=(.+)', dirs_file.read())
                cleaned_path = path_match.group(1).replace('"', '').replace('$HOME', '~')
                return os.path.expanduser(cleaned_path)
        except Exception:
            pass
        return os.getenv('XDG_DOWNLOAD_DIR', os.path.expanduser("~/Downloads"))


def user_data_dir(appname=None, appauthor=None, version=None, roaming=False):
    r"""Return full path to the user-specific data dir for this application.

        "appname" is the name of application.
            If None, just the sys.platform directory is returned.
        "appauthor" (only used on Windows) is the name of the
            appauthor or distributing body for this application. Typically
            it is the owning company name. This falls back to appname. You may
            pass False to disable it.
        "version" is an optional version path element to append to the
            path. You might want to use this if you want multiple versions
            of your app to be able to run independently. If used, this
            would typically be "<major>.<minor>".
            Only applied when appname is present.
        "roaming" (boolean, default False) can be set True to use the Windows
            roaming appdata directory. That means that for users on a Windows
            network setup for roaming profiles, this user data will be
            sync'd on login. See
            <http://technet.microsoft.com/en-us/library/cc766489(WS.10).aspx>
            for a discussion of issues.

    Typical user data directories are:
        Mac OS X: ~/Library/Application Support/<AppName>
        Unix:     ~/.local/share/<AppName>    # or in $XDG_DATA_HOME, if defined
        Win XP:   C:\Documents and Settings\<username>\Application Data\<AppAuthor>\<AppName>
        Win 7:    C:\Users\<username>\AppData\Local\<AppAuthor>\<AppName>

    For Unix, we follow the XDG spec and support $XDG_DATA_HOME.
    That means, by default "~/.local/share/<AppName>".
    """
    if sys.platform == "win32":
        if appauthor is None:
            appauthor = appname
        const = "CSIDL_APPDATA" if roaming else "CSIDL_LOCAL_APPDATA"
        path = os.path.normpath(_get_win_folder(const))
        if appname:
            if appauthor is not False:
                path = os.path.join(path, appauthor, appname)
            else:
                path = os.path.join(path, appname)
    elif sys.platform == "darwin":
        path = os.path.expanduser("~/Library/Application Support/")
        if appname:
            path = os.path.join(path, appname)
    else:
        path = os.getenv("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        if appname:
            path = os.path.join(path, appname)
    if appname and version:
        path = os.path.join(path, version)
    return path


def user_config_dir(appname=None, appauthor=None, version=None, roaming=False):
    r"""Return full path to the user-specific config dir for this application.

        "appname" is the name of application.
            If None, just the sys.platform directory is returned.
        "appauthor" (only used on Windows) is the name of the
            appauthor or distributing body for this application. Typically
            it is the owning company name. This falls back to appname. You may
            pass False to disable it.
        "version" is an optional version path element to append to the
            path. You might want to use this if you want multiple versions
            of your app to be able to run independently. If used, this
            would typically be "<major>.<minor>".
            Only applied when appname is present.
        "roaming" (boolean, default False) can be set True to use the Windows
            roaming appdata directory. That means that for users on a Windows
            network setup for roaming profiles, this user data will be
            sync'd on login. See
            <http://technet.microsoft.com/en-us/library/cc766489(WS.10).aspx>
            for a discussion of issues.

    Typical user config directories are:
        Mac OS X:               ~/Library/Preferences/<AppName>
        Unix:                   ~/.config/<AppName>     # or in $XDG_CONFIG_HOME, if defined
        Win *:                  same as user_data_dir

    For Unix, we follow the XDG spec and support $XDG_CONFIG_HOME.
    That means, by default "~/.config/<AppName>".
    """
    if sys.platform == "win32":
        path = user_data_dir(appname, appauthor, None, roaming)
    elif sys.platform == "darwin":
        path = os.path.expanduser("~/Library/Preferences/")
        if appname:
            path = os.path.join(path, appname)
    else:
        path = os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        if appname:
            path = os.path.join(path, appname)
    if appname and version:
        path = os.path.join(path, version)
    return path


def _get_win_folder(csidl_name):
    import ctypes  # pylint: disable=import-outside-toplevel

    csidl_const = {
        "CSIDL_APPDATA": 26,
        "CSIDL_COMMON_APPDATA": 35,
        "CSIDL_LOCAL_APPDATA": 28,
    }[csidl_name]

    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl_const, None, 0, buf)

    # Downgrade to short path name if have highbit chars. See
    # <http://bugs.activestate.com/show_bug.cgi?id=85099>.
    has_high_char = False
    for c in buf:
        if ord(c) > 255:
            has_high_char = True
            break
    if has_high_char:
        buf2 = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(buf.value, buf2, 1024):
            buf = buf2

    return buf.value


def _get_win_download_folder():
    import ctypes  # pylint: disable=import-outside-toplevel
    from ctypes import windll, wintypes  # pylint: disable=import-outside-toplevel
    from uuid import UUID  # pylint: disable=import-outside-toplevel

    class GUID(ctypes.Structure):
        _fields_ = [
            ("data1", wintypes.DWORD),
            ("data2", wintypes.WORD),
            ("data3", wintypes.WORD),
            ("data4", wintypes.BYTE * 8)
        ]

        def __init__(self, uuidstr):
            ctypes.Structure.__init__(self)
            uuid = UUID(uuidstr)
            self.data1, self.data2, self.data3, \
                self.data4[0], self.data4[1], rest = uuid.fields
            for i in range(2, 8):
                self.data4[i] = rest >> (8-i-1)*8 & 0xff

    SHGetKnownFolderPath = windll.shell32.SHGetKnownFolderPath  # pylint: disable=invalid-name
    SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)
    ]

    FOLDERID_Downloads = '{374DE290-123F-4565-9164-39C4925E467B}'  # pylint: disable=invalid-name
    guid = GUID(FOLDERID_Downloads)
    pathptr = ctypes.c_wchar_p()

    if SHGetKnownFolderPath(ctypes.byref(guid), 0, 0, ctypes.byref(pathptr)):
        raise Exception('Failed to get download directory.')

    return pathptr.value
