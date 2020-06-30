import os
import codecs
from setuptools import setup, find_packages


def read(relative_path):
    here = os.path.abspath(os.path.dirname(__file__))
    with codecs.open(os.path.join(here, relative_path), 'r') as fp:
        return fp.read()


def get_version(relative_path):
    for line in read(relative_path).splitlines():
        if line.startswith('__version__'):
            return line.split('"')[1]
    else:
        raise RuntimeError("Unable to find version string.")


setup(
    name='lbry',
    version=get_version('lbry/__init__.py'),
    author="LBRY Inc.",
    author_email="hello@lbry.com",
    url="https://lbry.com",
    description="A decentralized media library and marketplace",
    long_description=read('README.md'),
    long_description_content_type="text/markdown",
    keywords="lbry protocol media",
    license='MIT',
    python_requires='>=3.7',
    packages=find_packages(exclude=('tests',)),
    zip_safe=False,
    entry_points={
        'console_scripts': [
            'lbrynet=lbry.cli:main',
        ],
    },
    install_requires=[
        'aiohttp==3.5.4',
        'aioupnp==0.0.17',
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
        'pyyaml==5.3.1',
        'docopt==0.6.2',
        'hachoir',
        'multidict==4.6.1',
        'coincurve==11.0.0',
        'attrs==18.2.0',
        'pyzmq==18.1.1',
        'sqlalchemy@git+https://github.com/sqlalchemy/sqlalchemy.git',
        'chiabip158@git+https://github.com/Chia-Network/chiabip158.git',
        'tqdm',
    ],
    extras_require={
        'ui': ['pyside2'],
        'postgres': ['psycopg2', 'pgcopy'],
        'lint': ['mypy', 'pylint'],
        'test': ['coverage'],
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
