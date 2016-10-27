#!/usr/bin/env python

import os
from setuptools import setup
from lbrynet.conf import settings

APP = [os.path.join('lbrygui', 'main.py')]
DATA_FILES = []
DATA_FILES.append('app.icns')

OPTIONS = {
    'iconfile': settings.ICON_PATH,
    'plist': {
        'CFBundleIdentifier': 'io.lbry.LBRY',
        'LSUIElement': True,
    },
    'packages': [
        'lbrynet', 'lbryum', 'requests', 'unqlite', 'certifi',
        'pkg_resources', 'json', 'jsonrpc', 'seccure',
    ],
}


setup(
    name=settings.APP_NAME,
    app=APP,
    options={'py2app': OPTIONS},
    data_files=DATA_FILES,
)
