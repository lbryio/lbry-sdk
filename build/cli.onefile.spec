# -*- mode: python -*-
import platform
import os

dir = 'build';
cwd = os.getcwd()
if os.path.basename(cwd) != dir:
    raise Exception('pyinstaller build needs to be run from the ' + dir + ' directory')
repo_base = os.path.abspath(os.path.join(cwd, '..'))

execfile(os.path.join(cwd, "entrypoint.py")) # ghetto import


system = platform.system()
if system == 'Darwin':
    icns = os.path.join(repo_base, 'build', 'icon.icns')
elif system == 'Linux':
    icns = os.path.join(repo_base, 'build', 'icons', '256x256.png')
elif system == 'Windows':
    icns = os.path.join(repo_base, 'build', 'icons', 'lbry256.ico')
else:
    print 'Warning: System {} has no icons'.format(system)
    icns = None


a = Entrypoint('lbrynet', 'console_scripts', 'lbrynet-cli', pathex=[cwd], datas=datas)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='lbrynet-cli',
    debug=False,
    strip=False,
    upx=True,
    console=True,
    icon=icns
)
