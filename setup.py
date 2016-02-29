#!/usr/bin/env python

import ez_setup
ez_setup.use_setuptools()
from setuptools import setup, find_packages
import sys

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
                  'lbrynet-daemon = lbrynet.lbrynet_daemon.LBRYDaemon:main',
                  'stop-lbrynet-daemon = lbrynet.lbrynet_daemon.LBRYDaemon:stop']

if sys.platform == 'darwin':
    console_scripts.append('lbrynet-daemon-status = lbrynet.lbrynet_daemon.LBRYOSXStatusBar:main')


setup(name='lbrynet',
      version='0.0.4',
      packages=find_packages(),
      install_requires=['six>=1.9.0', 'pycrypto', 'twisted', 'miniupnpc', 'yapsy', 'seccure', 'python-bitcoinrpc==0.1', 'txJSON-RPC', 'requests>=2.4.2', 'unqlite==0.2.0', 'leveldb', 'lbryum'],
      entry_points={'console_scripts': console_scripts},
      data_files=[
          ('lbrynet/lbrynet_console/plugins',
           [
               'lbrynet/lbrynet_console/plugins/blindrepeater.yapsy-plugin',
           ]
           ),
          ('lbrynet/lbrynet_gui',
           [
               'lbrynet/lbrynet_gui/close2.gif',
               'lbrynet/lbrynet_gui/lbry-dark-242x80.gif',
               'lbrynet/lbrynet_gui/lbry-dark-icon.xbm',
               'lbrynet/lbrynet_gui/lbry-dark-icon.ico',
               'lbrynet/lbrynet_gui/drop_down.gif',
               'lbrynet/lbrynet_gui/show_options.gif',
               'lbrynet/lbrynet_gui/hide_options.gif',
               'lbrynet/lbrynet_gui/lbry.conf',
           ]
           )
      ],
      dependency_links=['https://github.com/lbryio/lbryum/tarball/master/#egg=lbryum'],
      )