import os
import platform
import subprocess
import sys
import zipfile


def main():
    this_dir = os.path.dirname(os.path.realpath(__file__))
    tag = subprocess.check_output(['git', 'describe']).strip()
    zipfilename = 'lbrynet-daemon-{}-{}.zip'.format(tag, get_system_label())
    full_filename = os.path.join(this_dir, 'dist', zipfilename)
    executables = ['lbrynet-daemon', 'lbrynet-cli']
    ext = '.exe' if platform.system() == 'Windows' else ''
    with zipfile.ZipFile(full_filename, 'w') as myzip:
        for executable in executables:
            myzip.write(os.path.join(this_dir, 'dist', executable + ext), executable + ext)


def get_system_label():
    system = platform.system()
    if system == 'Darwin':
        return 'macos'
    else:
        return system.lower()


if __name__ == '__main__':
    sys.exit(main())
