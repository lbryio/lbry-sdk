import os
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
    long_description=open(os.path.join(os.path.dirname(__file__), 'README.md'),
                          encoding='utf-8').read(),
    long_description_content_type="text/markdown",
    keywords='wallet,crypto,currency,money,bitcoin,lbry',
    classifiers=(
        'Framework :: AsyncIO',
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
    python_requires='>=3.6',
    install_requires=(
        'aiorpcx',
        'coincurve',
        'pbkdf2',
        'cryptography'
    ),
    extras_require={
        'test': (
            'mock',
        )
    }
)
