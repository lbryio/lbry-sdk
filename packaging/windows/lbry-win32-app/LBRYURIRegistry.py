import _winreg as winreg
import os


def main():
    lbry_path = os.path.join(os.environ["ProgramFiles"], "LBRY", "LBRY.exe")

    key_url = 'lbry'
    try:
        key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key_url, 0, winreg.KEY_ALL_ACCESS)
    except:
        key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_url)
    winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "URL:LBRY Protocol")
    winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    winreg.CloseKey(key)

    key_icon = os.path.join('lbry', 'DefaultIcon')
    try:
        key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key_icon, 0, winreg.KEY_ALL_ACCESS)
    except:
        key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_icon)
    winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "\"LBRY.exe,1\"")
    winreg.CloseKey(key)

    key_command = os.path.join('lbry', 'shell', 'open', 'command')
    try:
        key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key_command, 0, winreg.KEY_ALL_ACCESS)
    except:
        key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_command)
    winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "\"{0}\" \"%1\"".format(lbry_path))
    winreg.CloseKey(key)

if __name__ == "__main__":
    main()
