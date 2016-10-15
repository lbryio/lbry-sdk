from setuptools import setup
import os
from lbrynet.conf import PROTOCOL_PREFIX

APP = [os.path.join('lbry_uri_handler', 'LBRYURIHandler.py')]
DATA_FILES = []
OPTIONS = {'argv_emulation': True,
           'packages': ['jsonrpc'],
           'plist': {
               'LSUIElement': True,
               'CFBundleIdentifier': 'io.lbry.LBRYURIHandler',
               'CFBundleURLTypes': [
                    {
                    'CFBundleURLTypes': 'LBRYURIHandler',
                    'CFBundleURLSchemes': [PROTOCOL_PREFIX]
                    }
               ]
           }
        }

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)