#!/usr/bin/env python

import sys
import os
import site
from lbrynet import __version__


base_dir = os.path.abspath(os.path.dirname(__file__))
package_name = "lbrynet"
dist_name = "LBRY"
description = "A decentralized media library and marketplace"
author = "LBRY, Inc"
url = "lbry.io"
maintainer = "Jack Robison"
maintainer_email = "jack@lbry.io"
keywords = "LBRY"


# TODO: find a way to keep this in sync with requirements.txt
#
# Note though that this list is intentionally less restrictive than
# requirements.txt. This is only the libraries that are direct
# dependencies of the lbrynet library.  requirements.txt includes
# dependencies of dependencies and specific versions that we know
# all work together.
# See https://packaging.python.org/requirements/ for more details.
requires = [
    'Twisted',
    'appdirs',
    'base58',
    'envparse',
    'jsonrpc',
    'jsonschema',
    'lbryum>=2.7.6',
    'miniupnpc',
    'pycrypto',
    'pyyaml',
    'requests',
    'requests_futures',
    'seccure',
    'simplejson',
    'txJSON-RPC',
    'zope.interface',
]


console_scripts = [
    'lbrynet-daemon = lbrynet.lbrynet_daemon.DaemonControl:start',
    'stop-lbrynet-daemon = lbrynet.lbrynet_daemon.DaemonControl:stop',
    'lbrynet-cli = lbrynet.lbrynet_daemon.DaemonCLI:main'
]


def package_files(directory):
    for path, _, filenames in os.walk(directory):
        for filename in filenames:
            yield os.path.join('..', path, filename)


from setuptools import setup, find_packages


setup(name=package_name,
      description=description,
      version=__version__,
      maintainer=maintainer,
      maintainer_email=maintainer_email,
      url=url,
      author=author,
      keywords=keywords,
      packages=find_packages(base_dir, exclude=['tests']),
      install_requires=requires,
      entry_points={'console_scripts': console_scripts},
      package_data={
          package_name: list(package_files('lbrynet/resources/ui'))
      },
      zip_safe=False,
)
