import os
from setuptools import setup

APP = [os.path.join('lbrynet', 'lbrynet_daemon', 'LBRYOSXStatusBar.py')]
DATA_FILES = []
OPTIONS = {
    'argv_emulation': True,
    'iconfile': 'app.icns',
    'plist': {
        'LSUIElement': True,
    },
    'includes': ['rumps']
}


setup(
    name='LBRY',
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)