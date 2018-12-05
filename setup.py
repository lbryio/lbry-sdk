import os
import sys
from setuptools import setup, find_packages

import torba

BASE = os.path.dirname(__file__)
with open(os.path.join(BASE, 'README.md'), encoding='utf-8') as fh:
    long_description = fh.read()

REQUIRES = [
    'aiohttp',
    'coincurve',
    'pbkdf2',
    'cryptography',
    'attrs',
    'plyvel',
    'pylru'
]
if sys.platform.startswith('win32'):
    REQUIRES.remove('plyvel')


setup(
    name='torba',
    version=torba.__version__,
    url='https://github.com/lbryio/torba',
    license='MIT',
    author='LBRY Inc.',
    author_email='hello@lbry.io',
    description='Wallet client/server framework for bitcoin based currencies.',
    long_description=long_description,
    long_description_content_type="text/markdown",
    keywords='wallet,crypto,currency,money,bitcoin,electrum,electrumx',
    classifiers=[
        'Framework :: AsyncIO',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Operating System :: OS Independent',
        'Topic :: Internet',
        'Topic :: Software Development :: Testing',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: System :: Benchmark',
        'Topic :: System :: Distributed Computing',
        'Topic :: Utilities',
    ],
    packages=find_packages(exclude=('tests',)),
    python_requires='>=3.6',
    install_requires=REQUIRES,
    extras_require={
        'gui': (
            'pyside2',
        )
    },
    entry_points={
        'console_scripts': [
            'torba-client=torba.client.cli:main',
            'torba-server=torba.server.cli:main',
            'orchstr8=torba.orchstr8.cli:main',
        ],
        'gui_scripts': [
            'torba=torba.ui:main [gui]',
            'torba-workbench=torba.workbench:main [gui]',
        ]
    }
)
