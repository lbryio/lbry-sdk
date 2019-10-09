import os
from lbry import __name__, __version__
from setuptools import setup, find_packages

BASE = os.path.dirname(__file__)
README_PATH = os.path.join(BASE, 'README.md')

setup(
    name=__name__,
    version=__version__,
    author="LBRY Inc.",
    author_email="hello@lbry.com",
    url="https://lbry.com",
    description="A decentralized media library and marketplace",
    long_description=open(README_PATH, encoding='utf-8').read(),
    long_description_content_type="text/markdown",
    keywords="lbry protocol media",
    license='MIT',
    python_requires='>=3.7',
    packages=find_packages(exclude=('tests',)),
    zip_safe=False,
    entry_points={
        'console_scripts': 'lbrynet=lbry.extras.cli:main'
    },
    install_requires=[
        'torba',
        'aiohttp==3.5.4',
        'aioupnp==0.0.14',
        'appdirs==1.4.3',
        'certifi>=2018.11.29',
        'colorama==0.3.7',
        'distro==1.4.0',
        'base58==1.0.0',
        'cffi==1.12.1',
        'cryptography==2.5',
        'protobuf==3.6.1',
        'msgpack==0.6.1',
        'ecdsa==0.13.3',
        'pyyaml==4.2b1',
        'docopt==0.6.2',
        'hachoir',
    ],
)
