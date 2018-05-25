import os
import re
from setuptools import setup, find_packages

init_file = open(os.path.join(os.path.dirname(__path__), 'torba', '__init__.py')).read()
version = re.search('\d+\.\d+\.\d+', init_file).group()

setup(
    name='torba',
    version=version,
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
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Operating System :: OS Independent',
        'Topic :: Internet',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: System :: Distributed Computing',
        'Topic :: Utilities',
    ),
    packages=find_packages(exclude=('tests',)),
    include_package_data=True,
    python_requires='>=2.7,>=3.6',
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
