from setuptools import setup
import os

APP = [os.path.join('lbrynet', 'lbrynet_daemon', 'Apps', 'LBRYURIHandler.py')]
DATA_FILES = []
OPTIONS = {'argv_emulation': True,
           'packages': ['jsonrpc'],
           'plist': {
               'LSUIElement': True,
               'CFBundleURLTypes': [
                    {
                    'CFBundleURLTypes': 'LBRYURIHandler',
                    'CFBundleURLSchemes': ['lbry']
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