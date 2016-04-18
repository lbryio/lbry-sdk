#!/usr/bin/env python

from lbrynet import __version__

import ez_setup
ez_setup.use_setuptools()
import sys
import os
from setuptools import setup, find_packages

base_dir = os.path.abspath(os.path.dirname(__file__))


console_scripts = ['lbrynet-console = lbrynet.lbrynet_console.LBRYConsole:launch_lbry_console',
                  'lbrynet-stdin-uploader = lbrynet.lbrynet_console.LBRYStdinUploader:launch_stdin_uploader',
                  'lbrynet-stdout-downloader = lbrynet.lbrynet_console.LBRYStdoutDownloader:launch_stdout_downloader',
                  'lbrynet-create-network = lbrynet.create_network:main',
                  'lbrynet-launch-node = lbrynet.dht.node:main',
                  'lbrynet-launch-rpc-node = lbrynet.rpc_node:main',
                  'lbrynet-rpc-node-cli = lbrynet.node_rpc_cli:main',
                  'lbrynet-gui = lbrynet.lbrynet_gui.gui:start_gui',
                  'lbrynet-lookup-hosts-for-hash = lbrynet.dht_scripts:get_hosts_for_hash_in_dht',
                  'lbrynet-announce_hash_to_dht = lbrynet.dht_scripts:announce_hash_to_dht',
                  'lbrynet-daemon = lbrynet.lbrynet_daemon.LBRYDaemonControl:start',
                  'stop-lbrynet-daemon = lbrynet.lbrynet_daemon.LBRYDaemonControl:stop']

requires = ['pycrypto', 'twisted', 'miniupnpc', 'yapsy', 'seccure',
            'python-bitcoinrpc==0.1', 'txJSON-RPC', 'requests>=2.4.2', 'unqlite==0.2.0',
            'leveldb', 'lbryum', 'jsonrpc', 'simplejson', 'appdirs', 'six==1.9.0', 'base58']

gui_data_files = ['close2.gif', 'lbry-dark-242x80.gif', 'lbry-dark-icon.xbm', 'lbry-dark-icon.ico',
                  'drop_down.gif', 'show_options.gif', 'hide_options.gif', 'lbry.conf', 'lbry.png']
gui_data_paths = [os.path.join(base_dir, 'lbrynet', 'lbrynet_gui', f) for f in gui_data_files]

setup(name='lbrynet',
      description='A fully decentralized network for distributing data',
      version=__version__,
      maintainer='Jimmy Kiselak',
      maintainer_email='jimmy@lbry.io',
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
          ('lbrynet/lbrynet_gui', gui_data_paths)
      ],
      dependency_links=['https://github.com/lbryio/lbryum/tarball/master/#egg=lbryum'],
      )
