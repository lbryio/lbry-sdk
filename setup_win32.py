# -*- coding: utf-8 -*-
"""
To create local builds and distributable .msi, run the following command:
python setup_win32.py build bdist_msi
"""
import os
import sys

from cx_Freeze import setup, Executable
import requests.certs

from lbrynet import __version__

base_dir = os.path.abspath(os.path.dirname(__file__))

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
    'packages': ['Crypto', 'twisted', 'miniupnpc', 'yapsy', 'seccure',
                 'bitcoinrpc', 'txjsonrpc', 'requests', 'unqlite', 'lbryum',
                 'jsonrpc', 'simplejson', 'appdirs', 'six', 'base58', 'googlefinance',
                 'ecdsa', 'pbkdf2', 'qrcode', 'jsonrpclib',
                 'os', 'cython', 'win32api', 'pkg_resources', 'zope.interface',
                 'argparse', 'colorama', 'certifi'
                 # 'gmpy', 'wsgiref', 'slowaes', 'dnspython', 'protobuf', 'google', 'google.protobuf'
                 ],
    'excludes': ['collections.sys', 'collections._weakref', 'tkinter', 'tk', 'tcl'
                 'zope.interface._zope_interface_coptimizations', 'matplotlib', 'numpy', 'pillow', 'pandas'],
    'include_files': [(requests.certs.where(), 'cacert.pem')],
    'namespace_packages': ['zope']}

exe = Executable(
    script=os.path.join('lbrynet', 'lbrynet_daemon', 'LBRYDaemonControl.py'),
    # base='Win32GUI',
    icon=os.path.join('packaging', 'windows', 'icons', 'lbry256.ico'),
    # icon=os.path.join('lbry-dark-icon.ico'),
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
    # entry_points={'console_scripts': console_scripts},
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
