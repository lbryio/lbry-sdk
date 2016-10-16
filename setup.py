#!/usr/bin/env python

import sys
import os
import site
from lbrynet import __version__

LINUX = 1
DARWIN = 2
WINDOWS = 3

if sys.platform.startswith("linux"):
    platform = LINUX
elif sys.platform.startswith("darwin"):
    platform = DARWIN
elif sys.platform.startswith("win"):
    platform = WINDOWS
else:
    raise Exception("Unknown os: %s" % sys.platform)

base_dir = os.path.abspath(os.path.dirname(__file__))
package_name = "lbrynet"
dist_name = "LBRY"
description = "A decentralized media library and marketplace"
author = "LBRY, Inc"
url = "lbry.io"
maintainer = "Jack Robison"
maintainer_email = "jack@lbry.io"
keywords = "LBRY"

requires = [
    'pycrypto',
    'twisted',
    'miniupnpc',
    'yapsy',
    'seccure',
    'python-bitcoinrpc==0.1',
    'txJSON-RPC',
    'requests>=2.4.2',
    'unqlite==0.2.0',
    'lbryum',
    'jsonrpc',
    'simplejson',
    'jsonschema',
    'appdirs',
    'six==1.9.0',
    'base58',
    'googlefinance',
    'requests_futures',
    'PyYAML'
]

console_scripts = [
    # 'lbrynet-stdin-uploader = lbrynet.lbrynet_console.LBRYStdinUploader:launch_stdin_uploader',
    # 'lbrynet-stdout-downloader = lbrynet.lbrynet_console.LBRYStdoutDownloader:launch_stdout_downloader',
    # 'lbrynet-create-network = lbrynet.create_network:main',
    # 'lbrynet-launch-node = lbrynet.dht.node:main',
    # 'lbrynet-launch-rpc-node = lbrynet.rpc_node:main',
    # 'lbrynet-rpc-node-cli = lbrynet.node_rpc_cli:main',
    # 'lbrynet-lookup-hosts-for-hash = lbrynet.dht_scripts:get_hosts_for_hash_in_dht',
    # 'lbrynet-announce_hash_to_dht = lbrynet.dht_scripts:announce_hash_to_dht',
    'lbrynet-daemon = lbrynet.lbrynet_daemon.DaemonControl:start',
    'stop-lbrynet-daemon = lbrynet.lbrynet_daemon.DaemonControl:stop',
    'lbrynet-cli = lbrynet.lbrynet_daemon.DaemonCLI:main'
]

if platform == LINUX:
    import ez_setup
    ez_setup.use_setuptools()
    from setuptools import setup, find_packages

    requires.append('service-identity')

    setup(name=package_name,
          description=description,
          version=__version__,
          maintainer=maintainer,
          maintainer_email=maintainer_email,
          url=url,
          author=author,
          keywords=keywords,
          packages=find_packages(base_dir),
          install_requires=requires,
          entry_points={'console_scripts': console_scripts},
          data_files=[
              ('lbrynet/lbrynet_console/plugins',
               [
                   os.path.join(base_dir, 'lbrynet', 'lbrynet_console', 'plugins',
                                'blindrepeater.yapsy-plugin')
               ]
               ),
          ],
          dependency_links=['https://github.com/lbryio/lbryum/tarball/master/#egg=lbryum'],
          )

elif platform == DARWIN:
    import ez_setup

    ez_setup.use_setuptools()
    from setuptools import setup, find_packages

    setup(name=package_name,
          description=description,
          version=__version__,
          maintainer=maintainer,
          maintainer_email=maintainer_email,
          url=url,
          author=author,
          keywords=keywords,
          packages=find_packages(base_dir),
          install_requires=requires,
          entry_points={'console_scripts': console_scripts},
          data_files=[
              ('lbrynet/lbrynet_console/plugins',
               [
                   os.path.join(base_dir, 'lbrynet', 'lbrynet_console', 'plugins',
                                'blindrepeater.yapsy-plugin')
               ]
               ),
          ],
          dependency_links=['https://github.com/lbryio/lbryum/tarball/master/#egg=lbryum'],
          )

elif platform == WINDOWS:
    import opcode
    import pkg_resources
    from cx_Freeze import setup, Executable
    import requests.certs

    app_dir = os.path.join('packaging', 'windows', 'lbry-win32-app')
    daemon_dir = os.path.join('lbrynet', 'lbrynet_daemon')
    win_icon = os.path.join(app_dir, 'icons', 'lbry256.ico')
    wordlist_path = pkg_resources.resource_filename('lbryum', 'wordlist')

    # Allow virtualenv to find distutils of base python installation
    distutils_path = os.path.join(os.path.dirname(opcode.__file__), 'distutils')

    schemas = os.path.join(site.getsitepackages()[1], "jsonschema", "schemas")
    onlyfiles = [f for f in os.listdir(schemas) if os.path.isfile(os.path.join(schemas, f))]
    zipincludes = [(os.path.join(schemas, f), os.path.join("jsonschema", "schemas", f)) for f in onlyfiles]

    def find_data_file(filename):
        if getattr(sys, 'frozen', False):
            # The application is frozen
            data_dir = os.path.dirname(sys.executable)
        else:
            # The application is not frozen
            # Change this bit to match where you store your data files:
            data_dir = os.path.dirname(__file__)
        return os.path.join(data_dir, filename)

    shortcut_table = [
        ('LBRYShortcut',  # Shortcut
         'DesktopFolder',  # Directory
         'LBRY',  # Name
         'TARGETDIR',  # Component
         '[TARGETDIR]\{0}.exe'.format(dist_name),  # Target
         None,  # Arguments
         description,  # Description
         None,  # Hotkey
         None,  # Icon
         None,  # IconIndex
         None,  # ShowCmd
         'TARGETDIR',  # WkDir
         ),
        # ('DaemonShortcut',  # Shortcut
        #  'DesktopFolder',  # Directory
        #  'lbrynet-daemon',  # Name
        #  'TARGETDIR',  # Component
        #  '[TARGETDIR]\lbrynet-daemon.exe',  # Target
        #  '--log-to-console',  # Arguments
        #  description,  # Description
        #  None,  # Hotkey
        #  None,  # Icon
        #  None,  # IconIndex
        #  None,  # ShowCmd
        #  'TARGETDIR',  # WkDir
        #  ),
        # ('DaemonCLIShortcut',  # Shortcut
        #  'DesktopFolder',  # Directory
        #  'lbrynet-cli',  # Name
        #  'TARGETDIR',  # Component
        #  '[TARGETDIR]\lbrynet-cli.exe',  # Target
        #  None,  # Arguments
        #  description,  # Description
        #  None,  # Hotkey
        #  None,  # Icon
        #  None,  # IconIndex
        #  None,  # ShowCmd
        #  'TARGETDIR',  # WkDir
        #  ),
        ('ProgramMenuLBRYShortcut',  # Shortcut
         'ProgramMenuFolder',  # Directory
         # r'[ProgramMenuFolder]\lbrynet',  # Directory
         'LBRY',  # Name
         'TARGETDIR',  # Component
         '[TARGETDIR]\{0}.exe'.format(dist_name),  # Target
         None,  # Arguments
         description,  # Description
         None,  # Hotkey
         None,  # Icon
         None,  # IconIndex
         None,  # ShowCmd
         'TARGETDIR',  # WkDir
         ),
        ('ProgramMenuDaemonShortcut',  # Shortcut
         'ProgramMenuFolder',  # Directory
         # r'[ProgramMenuFolder]\lbrynet',  # Directory
         'lbrynet-daemon',  # Name
         'TARGETDIR',  # Component
         '[TARGETDIR]\lbrynet-daemon.exe',  # Target
         '--log-to-console',  # Arguments
         description,  # Description
         None,  # Hotkey
         None,  # Icon
         None,  # IconIndex
         None,  # ShowCmd
         'TARGETDIR',  # WkDir
         ),
        ('ProgramMenuDaemonCLIShortcut',  # Shortcut
         'ProgramMenuFolder',  # Directory
         # r'[ProgramMenuFolder]\lbrynet',  # Directory
         'lbrynet-cli',  # Name
         'TARGETDIR',  # Component
         '[TARGETDIR]\lbrynet-cli.exe',  # Target
         None,  # Arguments
         description,  # Description
         None,  # Hotkey
         None,  # Icon
         None,  # IconIndex
         None,  # ShowCmd
         'TARGETDIR',  # WkDir
         ),
        ]

    msi_data = {"Shortcut": shortcut_table}

    bdist_msi_options = {
        'upgrade_code': '{18c0e933-ad08-44e8-a413-1d0ed624c100}',
        'add_to_path': True,
        # Default install path is 'C:\Program Files\' for 32-bit or 'C:\Program Files (x86)\' for 64-bit
        # 'initial_target_dir': r'[LocalAppDataFolder]\{0}'.format(name),
        'data': msi_data
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
                     'jsonschema',
                     'six',
                     'aes',
                     'txjsonrpc',
                     'unqlite',
                     'wsgiref',
                     'zope.interface',
                     'os',
                     'pkg_resources',
                     'yaml'
                     ],
        'excludes': ['distutils', 'collections.sys', 'collections._weakref', 'collections.abc',
                     'Tkinter', 'tk', 'tcl', 'PyQt4', 'nose', 'mock'
                     'zope.interface._zope_interface_coptimizations', 'leveldb'],
        'include_files': [(distutils_path, 'distutils'), (requests.certs.where(), 'cacert.pem'),
                          (os.path.join(app_dir, 'icons', 'lbry16.ico'), os.path.join('icons', 'lbry16.ico')),
                          (os.path.join(app_dir, 'icons', 'lbry256.ico'), os.path.join('icons', 'lbry256.ico')),
                          (os.path.join(wordlist_path, 'chinese_simplified.txt'),
                           os.path.join('wordlist', 'chinese_simplified.txt')),
                          (os.path.join(wordlist_path, 'english.txt'), os.path.join('wordlist', 'english.txt')),
                          (os.path.join(wordlist_path, 'japanese.txt'), os.path.join('wordlist', 'japanese.txt')),
                          (os.path.join(wordlist_path, 'portuguese.txt'), os.path.join('wordlist', 'portuguese.txt')),
                          (os.path.join(wordlist_path, 'spanish.txt'), os.path.join('wordlist', 'spanish.txt'))
                          ],
        'namespace_packages': ['zope', 'google'],
        "zip_includes": zipincludes}

    tray_app = Executable(
        script=os.path.join(app_dir, 'LBRYWin32App.py'),
        base='Win32GUI',
        icon=win_icon,
        compress=True,
        # shortcutName=dist_name,
        # shortcutDir='DesktopFolder',
        targetName='{0}.exe'.format(dist_name)
    )

    daemon_exe = Executable(
        script=os.path.join(daemon_dir, 'DaemonControl.py'),
        icon=win_icon,
        # shortcutName="lbrynet-daemon",
        # shortcutDir='DesktopFolder',
        targetName='lbrynet-daemon.exe'
    )

    cli_exe = Executable(
        script=os.path.join(daemon_dir, 'DaemonCLI.py'),
        icon=win_icon,
        # shortcutName="lbrynet-cli",
        # shortcutDir='DesktopFolder',
        targetName='lbrynet-cli.exe'
    )

    setup(
        name=package_name,
        description=description,
        version=__version__,
        maintainer=maintainer,
        maintainer_email=maintainer_email,
        url=url,
        author=author,
        keywords=keywords,
        data_files=[],
        options={'build_exe': build_exe_options,
                 'bdist_msi': bdist_msi_options},
        executables=[
            tray_app,
            daemon_exe,
            cli_exe
        ],
    )
