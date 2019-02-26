import os
from lbrynet import __name__, __version__
from setuptools import setup, find_packages

BASE = os.path.dirname(__file__)
README_PATH = os.path.join(BASE, 'README.md')

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
        'aiohttp==3.4.4',
        'aioupnp',
        'appdirs==1.4.3',
        'colorama==0.3.7',
        'distro==1.4.0',
        'base58==1.0.0',
        'cffi==1.12.1',
        'cryptography==2.5',
        'protobuf==3.6.1',
        'msgpack==0.6.1',
        'jsonschema==2.6.0',
        'ecdsa==0.13',
        'torba',
        'pyyaml==3.13',
        'docopt==0.6.2',
    ],
)
