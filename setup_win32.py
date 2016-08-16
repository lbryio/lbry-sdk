# -*- coding: utf-8 -*-
"""
To create local builds and distributable .msi, run the following command:
python setup_win32.py build bdist_msi
"""
import opcode
import os
import pkg_resources
import sys

from cx_Freeze import setup, Executable
import requests.certs

from lbrynet import __version__

wordlist_path = pkg_resources.resource_filename('lbryum', 'wordlist')

# protobuf needs a blank __init__.py in the site-packages/google folder for cx_freeze to find
protobuf_path = os.path.dirname(os.path.dirname(pkg_resources.resource_filename('google.protobuf', '__init__.py')))
protobuf_init = os.path.join(protobuf_path, '__init__.py')
if not os.path.isfile(protobuf_init):
    with open(protobuf_init, 'w') as f:
        f.write('')

base_dir = os.path.abspath(os.path.dirname(__file__))

# Allow virtualenv to find distutils of base python installation
distutils_path = os.path.join(os.path.dirname(opcode.__file__), 'distutils')


def find_data_file(filename):
    if getattr(sys, 'frozen', False):
        # The application is frozen
        data_dir = os.path.dirname(sys.executable)
    else:
        # The application is not frozen
        # Change this bit to match where you store your data files:
        data_dir = os.path.dirname(__file__)
    return os.path.join(data_dir, filename)

console_scripts = ['lbrynet-stdin-uploader = lbrynet.lbrynet_console.LBRYStdinUploader:launch_stdin_uploader',
                  'lbrynet-stdout-downloader = lbrynet.lbrynet_console.LBRYStdoutDownloader:launch_stdout_downloader',
                  'lbrynet-create-network = lbrynet.create_network:main',
                  'lbrynet-launch-node = lbrynet.dht.node:main',
                  'lbrynet-launch-rpc-node = lbrynet.rpc_node:main',
                  'lbrynet-rpc-node-cli = lbrynet.node_rpc_cli:main',
                  'lbrynet-lookup-hosts-for-hash = lbrynet.dht_scripts:get_hosts_for_hash_in_dht',
                  'lbrynet-announce_hash_to_dht = lbrynet.dht_scripts:announce_hash_to_dht',
                  'lbrynet-daemon = lbrynet.lbrynet_daemon.LBRYDaemonControl:start',
                  'stop-lbrynet-daemon = lbrynet.lbrynet_daemon.LBRYDaemonControl:stop',
                  'lbrynet-cli = lbrynet.lbrynet_daemon.LBRYDaemonCLI:main']

shortcut_table = [
    ('DesktopShortcut',  # Shortcut
     'DesktopFolder',  # Directory
     'lbrynet',  # Name
     'TARGETDIR',  # Component
     '[TARGETDIR]\lbrynet.exe',  # Target
     None,  # Arguments
     None,  # Description
     None,  # Hotkey
     os.path.join('lbry-dark-icon.ico'),  # Icon
     None,  # IconIndex
     None,  # ShowCmd
     'TARGETDIR',  # WkDir
     ),
    ]

# Now create the table dictionary
msi_data = {'Shortcut': shortcut_table}

bdist_msi_options = {
    # 'upgrade_code': '{66620F3A-DC3A-11E2-B341-002219E9B01F}',
    'add_to_path': False,
    'initial_target_dir': r'[LocalAppDataFolder]\lbrynet',
    'data': msi_data,
    }

build_exe_options = {
    'include_msvcr': True,
    'includes': [],
    'packages': ['cython',
                 'twisted',
                 'yapsy',
                 'appdirs',
                 'argparse',
                 'base58',
                 'colorama',
                 'cx_Freeze',
                 'dns',
                 'ecdsa',
                 'gmpy',
                 'googlefinance',
                 'jsonrpc',
                 'jsonrpclib',
                 'lbryum',
                 'loggly',
                 'miniupnpc',
                 'pbkdf2',
                 'google.protobuf',
                 'Crypto',
                 'bitcoinrpc',
                 'win32api',
                 'qrcode',
                 'requests',
                 'requests_futures',
                 'seccure',
                 'simplejson',
                 'six',
                 'aes',
                 'txjsonrpc',
                 'unqlite',
                 'wsgiref',
                 'zope.interface',
                 'os',
                 'pkg_resources'
                 ],
    'excludes': ['distutils', 'collections.sys', 'collections._weakref', 'collections.abc',
                 'Tkinter', 'tk', 'tcl', 'PyQt4'
                 'zope.interface._zope_interface_coptimizations'],
    'include_files': [(distutils_path, 'distutils'), (requests.certs.where(), 'cacert.pem'),
                      (os.path.join(wordlist_path, 'chinese_simplified.txt'), os.path.join('wordlist', 'chinese_simplified.txt')),
                      (os.path.join(wordlist_path, 'english.txt'), os.path.join('wordlist', 'english.txt')),
                      (os.path.join(wordlist_path, 'japanese.txt'), os.path.join('wordlist', 'japanese.txt')),
                      (os.path.join(wordlist_path, 'portuguese.txt'), os.path.join('wordlist', 'portuguese.txt')),
                      (os.path.join(wordlist_path, 'spanish.txt'), os.path.join('wordlist', 'spanish.txt'))
                      ],
    'namespace_packages': ['zope']}

exe = Executable(
    script=os.path.join('lbrynet', 'lbrynet_daemon', 'LBRYDaemonControl.py'),
    # base='Win32GUI',
    icon=os.path.join('packaging', 'windows', 'icons', 'lbry256.ico'),
    compress=True,
    shortcutName='lbrynet',
    shortcutDir='DesktopFolder',
    targetName='lbrynet.exe'
    # targetDir="LocalAppDataFolder"
    )

setup(
    name='lbrynet',
    version=__version__,
    description='A decentralized media library and marketplace',
    url='lbry.io',
    author='',
    keywords='LBRY',
    data_files=[
      ('lbrynet/lbrynet_console/plugins',
       [
           os.path.join(base_dir, 'lbrynet', 'lbrynet_console', 'plugins',
                        'blindrepeater.yapsy-plugin')
       ]
       ),
    ],
    options={'build_exe': build_exe_options,
             'bdist_msi': bdist_msi_options},
    executables=[exe],
    )
