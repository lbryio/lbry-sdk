import os
import sys
from lbry import __name__, __version__
from setuptools import setup, find_packages

BASE = os.path.dirname(__file__)
with open(os.path.join(BASE, 'README.md'), encoding='utf-8') as fh:
    long_description = fh.read()

PLYVEL = []
if sys.platform.startswith('linux'):
    PLYVEL.append('plyvel==1.0.5')

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
            'torba-server=lbry.wallet.server.cli:main',
            'orchstr8=lbry.wallet.orchstr8.cli:main',
        ],
    },
    install_requires=[
        'aiohttp==3.5.4',
        'aioupnp==0.0.17',
        'appdirs==1.4.3',
        'certifi>=2018.11.29',
        'colorama==0.3.7',
        'distro==1.4.0',
        'base58==1.0.0',
        'cffi==1.13.2',
        'cryptography==2.5',
        'protobuf==3.6.1',
        'msgpack==0.6.1',
        'prometheus_client==0.7.1',
        'ecdsa==0.13.3',
        'pyyaml==4.2b1',
        'docopt==0.6.2',
        'hachoir',
        'multidict==4.6.1',
        'coincurve==11.0.0',
        'pbkdf2==1.3',
        'attrs==18.2.0',
        'pylru==1.1.0'
    ] + PLYVEL,
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
