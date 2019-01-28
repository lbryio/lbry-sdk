from os.path import join, dirname, abspath
from pythonforandroid.toolchain import Bootstrap
from setuptools import setup, find_packages
from bootstrap import LBRYServiceBootstrap


Bootstrap.bootstraps = {
    'lbry-service': LBRYServiceBootstrap()
}


setup(
    name='lbryservice',
    version='0.1',
    author="LBRY Inc.",
    author_email="hello@lbry.io",
    url="https://lbry.io",
    description="Android Service for LBRY Network.",
    license='MIT',
    python_requires='>=3.7',
    packages=find_packages(),
    package_data={'service': ['*.py']},
    options={
        'apk': {
            'dist_name': 'lbry-service',
            'bootstrap': 'lbry-service',
            'package': 'io.lbry.service',
            'permissions': ['INTERNET'],
            'requirements': ','.join([
                # needed by aiohttp
                'multidict', 'yarl', 'async_timeout', 'chardet',
                # minimum needed by torba:
                'aiohttp', 'coincurve', 'pbkdf2', 'cryptography', 'attrs',
                abspath(join(dirname(__file__), '..', '..', 'torba')),
                # minimum needed by lbrynet
                'aioupnp', 'appdirs', 'distro', 'base58', 'jsonrpc', 'protobuf',
                'msgpack', 'jsonschema', 'ecdsa', 'pyyaml', 'docopt',
                abspath(join(dirname(__file__), '..')),
                'genericndkbuild', 'pyjnius', 'sqlite3', 'python3'
            ]),
            'android-api': '26',
            'ndk-api': '21',
            'ndk-version': 'r17c',
            'arch': 'armeabi-v7a',
            'sdk-dir': '/home/lex/projects/android',
            'ndk-dir': '/home/lex/projects/android/android-ndk-r17c/'
        }
    }
)
