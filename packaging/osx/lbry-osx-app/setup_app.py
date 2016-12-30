#!/usr/bin/env python

import os
from setuptools import setup
from lbrynet import conf

APP = [os.path.join('lbrygui', 'main.py')]
DATA_FILES = []
DATA_FILES.append('app.icns')

OPTIONS = {
    'iconfile': conf.ICON_PATH,
    'plist': {
        'CFBundleIdentifier': 'io.lbry.LBRY',
        'LSUIElement': True,
    },
    'packages': [
        'lbrynet', 'lbryum', 'requests', 'certifi',
        'pkg_resources', 'json', 'jsonrpc', 'seccure',
    ],
}


setup(
    name=conf.APP_NAME,
    app=APP,
    options={'py2app': OPTIONS},
    data_files=DATA_FILES,
)
