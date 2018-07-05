import os
import re
from setuptools import setup, find_packages

import torba

setup(
    name='torba',
    version=torba.__version__,
    url='https://github.com/lbryio/torba',
    license='MIT',
    author='LBRY Inc.',
    author_email='hello@lbry.io',
    description='Wallet library for bitcoin based currencies.',
    keywords='wallet,crypto,currency,money,bitcoin,lbry',
    classifiers=(
        'Framework :: Twisted',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Operating System :: OS Independent',
        'Topic :: Internet',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: System :: Distributed Computing',
        'Topic :: Utilities',
    ),
    packages=find_packages(exclude=('tests',)),
    include_package_data=True,
    python_requires='>=2.7',
    install_requires=(
        'twisted',
        'ecdsa',
        'pbkdf2',
        'cryptography',
        'typing'
    ),
    extras_require={
        'test': (
            'mock',
        )
    }
)
