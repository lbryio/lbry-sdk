import os
from lbrynet import __name__, __version__
from setuptools import setup, find_packages

BASE = os.path.dirname(__file__)
README_PATH = os.path.join(BASE, 'README.md')

SERVER_REQUIRES = (
    'msgpack',
    'torba[server]',
)

setup(
    name=__name__,
    version=__version__,
    author="LBRY Inc.",
    author_email="hello@lbry.io",
    url="https://lbry.io",
    description="A decentralized media library and marketplace",
    long_description=open(README_PATH, encoding='utf-8').read(),
    long_description_content_type="text/markdown",
    keywords="lbry protocol media",
    license='MIT',
    python_requires='>=3.6',
    packages=find_packages(exclude=('tests',)),
    zip_safe=False,
    entry_points={
        'console_scripts': 'lbrynet=lbrynet.extras.cli:main'
    },
    install_requires=[
        'aiohttp',
        'aioupnp',
        'twisted[tls]==18.7.0',
        'appdirs',
        'distro',
        'base58==1.0.0',
        'envparse',
        'jsonrpc',
        'cryptography',
        'protobuf==3.6.1',
        'jsonschema',
        'ecdsa',
        'torba',
        'pyyaml',
        'requests',
        'txJSON-RPC',
        'treq',
        'docopt',
        'colorama==0.3.7',
    ],
    extras_require={
        'wallet-server': SERVER_REQUIRES,
        'test': (
            'mock>=2.0,<3.0',
            'faker==0.8.17',
            'pytest',
            'pytest-asyncio',
            'pytest-xprocess',
        ) + SERVER_REQUIRES,
    }
)
