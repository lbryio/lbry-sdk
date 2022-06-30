import os
import sys
from lbry import __name__, __version__
from setuptools import setup, find_packages

BASE = os.path.dirname(__file__)
with open(os.path.join(BASE, 'README.md'), encoding='utf-8') as fh:
    long_description = fh.read()


ROCKSDB = []
if sys.platform.startswith('linux') or sys.platform.startswith('darwin'):
    ROCKSDB.append('lbry-rocksdb==0.8.2')


setup(
    name=__name__,
    version=__version__,
    author="LBRY Inc.",
    author_email="hello@lbry.com",
    url="https://lbry.com",
    description="A decentralized media library and marketplace",
    long_description=long_description,
    long_description_content_type="text/markdown",
    keywords="lbry protocol media",
    license='MIT',
    python_requires='>=3.7',
    packages=find_packages(exclude=('tests',)),
    zip_safe=False,
    entry_points={
        'console_scripts': [
            'lbrynet=lbry.extras.cli:main',
            'orchstr8=lbry.wallet.orchstr8.cli:main'
        ],
    },
    install_requires=[
        'aiohttp==3.7.4',
        'aioupnp==0.0.18',
        'appdirs==1.4.3',
        'certifi>=2021.10.08',
        'colorama==0.3.7',
        'distro==1.4.0',
        'base58==1.0.0',
        'cffi==1.13.2',
        'cryptography==2.5',
        'protobuf==3.17.2',
        'msgpack==0.6.1',
        'prometheus_client==0.7.1',
        'ecdsa==0.13.3',
        'pyyaml==5.3.1',
        'docopt==0.6.2',
        'hachoir==3.1.2',
        'multidict==4.6.1',
        'coincurve==15.0.0',
        'pbkdf2==1.3',
        'attrs==18.2.0',
        'pylru==1.1.0',
        'elasticsearch==7.10.1',
        'grpcio==1.38.0',
        'filetype==1.0.9',
    ] + ROCKSDB,
    extras_require={
        'torrent': ['lbry-libtorrent'],
        'lint': [
            'pylint==2.10.0'
        ],
        'test': [
            'coverage',
            'jsonschema==4.4.0',
        ],
        'hub': [
            'hub@git+https://github.com/lbryio/hub.git@9e3963ba23abf2f9ace4654089a7df1fd553f121'
        ]
    },
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
        'Topic :: System :: Distributed Computing',
        'Topic :: Utilities',
    ],
)
