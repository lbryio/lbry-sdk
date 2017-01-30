import _winreg as winreg
import os
import sys

import win32con
import win32gui


def main():
    try:
        install = 'remove' not in sys.argv[1]
    except:
        install = True
    lbry_path = os.path.join(os.environ["ProgramFiles"], "LBRY", "LBRY.exe")

    key_url = 'lbry'
    try:
        key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key_url, 0, winreg.KEY_ALL_ACCESS)
    except:
        key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_url)
    if install:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "URL:LBRY Protocol")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    else:
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_url)

    winreg.CloseKey(key)

    key_icon = os.path.join('lbry', 'DefaultIcon')
    try:
        key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key_icon, 0, winreg.KEY_ALL_ACCESS)
    except:
        key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_icon)
    if install:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "\"LBRY.exe,1\"")
    else:
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_icon)
    winreg.CloseKey(key)

    key_command = os.path.join('lbry', 'shell', 'open', 'command')
    try:
        key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key_command, 0, winreg.KEY_ALL_ACCESS)
    except:
        key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_command)
    if install:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "\"{0}\" \"%1\"".format(lbry_path))
    else:
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_command)
    winreg.CloseKey(key)

    win32gui.SendMessage(win32con.HWND_BROADCAST, win32con.WM_SETTINGCHANGE, 0, 'Environment')

if __name__ == "__main__":
    main()
