import os
from lbrynet import __name__, __version__
from setuptools import setup, find_packages

BASE = os.path.dirname(__file__)
README_PATH = os.path.join(BASE, 'README.md')//hello

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
        'console_scripts': 'lbrynet=lbrynet.cli:main'
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
        'lbryschema',
        'torba',
        'pyyaml',
        'requests',
        'txJSON-RPC',
        'treq',
        'docopt',
        'colorama==0.3.7',
        'six'
    ],
    extras_require={
        'test': (
            'mock>=2.0,<3.0',
            'faker==0.8.17',
            'orchstr8>=0.0.4'
        )
    }
)
