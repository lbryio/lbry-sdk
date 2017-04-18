# -*- mode: python -*-
import platform
import os

import lbryum


dir = 'build';
cwd = os.getcwd()
if os.path.basename(cwd) != dir:
    raise Exception('pyinstaller build needs to be run from the ' + dir + ' directory')
repo_base = os.path.abspath(os.path.join(cwd, '..'))


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


block_cipher = None


languages = (
    'chinese_simplified.txt', 'japanese.txt', 'spanish.txt',
    'english.txt', 'portuguese.txt'
)


datas = [
    (
        os.path.join(os.path.dirname(lbryum.__file__), 'wordlist', language),
        'lbryum/wordlist'
    )
    for language in languages
]


a = Analysis(
    ['daemon.py'],
    pathex=[cwd],
    binaries=None,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher
)


pyz = PYZ(
    a.pure, a.zipped_data,
    cipher=block_cipher
)


exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='lbrynet-daemon',
    debug=False,
    strip=False,
    upx=True,
    console=True,
    icon=icns
)
