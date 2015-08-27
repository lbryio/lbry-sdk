#!/usr/bin/env python

import ez_setup
ez_setup.use_setuptools()

from setuptools import setup, find_packages

setup(name='lbrynet',
      version='0.0.4',
      packages=find_packages(),
      install_requires=['pycrypto', 'twisted', 'miniupnpc', 'yapsy', 'seccure', 'python-bitcoinrpc', 'leveldb', 'txJSON-RPC', 'requests'],
      entry_points={
          'console_scripts': [
              'lbrynet-console = lbrynet.lbrynet_console.LBRYConsole:launch_lbry_console',
              'lbrynet-stdin-uploader = lbrynet.lbrynet_console.LBRYStdinUploader:launch_stdin_uploader',
              'lbrynet-stdout-downloader = lbrynet.lbrynet_console.LBRYStdoutDownloader:launch_stdout_downloader',
              'lbrynet-create-network = lbrynet.create_network:main',
              'lbrynet-launch-node = lbrynet.dht.node:main',
              'lbrynet-launch-rpc-node = lbrynet.rpc_node:main',
              'lbrynet-rpc-node-cli = lbrynet.node_rpc_cli:main',
              'lbrynet-gui = lbrynet.lbrynet_downloader_gui.downloader:start_downloader',
              'lbrynet-lookup-hosts-for-hash = lbrynet.dht_scripts:get_hosts_for_hash_in_dht',
              'lbrynet-announce_hash_to_dht = lbrynet.dht_scripts:announce_hash_to_dht',
          ]
      },
      data_files=[
          ('lbrynet/lbrynet_console/plugins',
           [
               'lbrynet/lbrynet_console/plugins/blindrepeater.yapsy-plugin',
           ]
           ),
          ('lbrynet/lbrynet_downloader_gui',
           [
               'lbrynet/lbrynet_downloader_gui/close2.gif',
               'lbrynet/lbrynet_downloader_gui/lbry-dark-242x80.gif',
               'lbrynet/lbrynet_downloader_gui/lbry-dark-icon.xbm',
               'lbrynet/lbrynet_downloader_gui/lbry-dark-icon.ico',
               'lbrynet/lbrynet_downloader_gui/drop_down.gif',
               'lbrynet/lbrynet_downloader_gui/show_options.gif',
               'lbrynet/lbrynet_downloader_gui/hide_options.gif',
           ]
           )
      ]
      )
