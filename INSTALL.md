# Installing LBRY

If only the JSON-RPC API server is needed, the recommended way to install LBRY is to use a pre-built binary. We provide binaries for all major operating systems. See the [README](README.md)!

These instructions are for installing LBRY from source, which is recommended if you are interested in doing development work or LBRY is not available on your operating system (godspeed, TempleOS users).

Here's a video walkthrough of this setup, which is itself hosted by the LBRY network and provided via [spee.ch](https://github.com/lbryio/spee.ch):
[![Setup for development](https://spee.ch/2018-10-04-17-13-54-017046806.png)](https://spee.ch/967f99344308f1e90f0620d91b6c93e4dfb240e0/lbrynet-dev-setup.mp4)

## Prerequisites

Running `lbrynet` from source requires Python 3.7. Get the installer for your OS [here](https://www.python.org/downloads/release/python-370/).

After installing Python 3.7, you'll need to install some additional libraries depending on your operating system.

Because of [issue #2769](https://github.com/lbryio/lbry-sdk/issues/2769)
at the moment the `lbrynet` daemon will only work correctly with Python 3.7.
If Python 3.8+ is used, the daemon will start but the RPC server
may not accept messages, returning the following:
```
Could not connect to daemon. Are you sure it's running?
```

### macOS

macOS users will need to install [xcode command line tools](https://developer.xamarin.com/guides/testcloud/calabash/configuring/osx/install-xcode-command-line-tools/) and [homebrew](http://brew.sh/).

These environment variables also need to be set:
```
PYTHONUNBUFFERED=1
EVENT_NOKQUEUE=1
```

Remaining dependencies can then be installed by running:
```
brew install python protobuf
```

Assistance installing Python3: https://docs.python-guide.org/starting/install3/osx/.

### Linux

On Ubuntu (we recommend 18.04 or 20.04), install the following:
```
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install build-essential python3.7 python3.7-dev git python3.7-venv libssl-dev python-protobuf
```

The [deadsnakes PPA](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa) provides Python 3.7
for those Ubuntu distributions that no longer have it in their
official repositories.

On Raspbian, you will also need to install `python-pyparsing`.

If you're running another Linux distro, install the equivalent of the above packages for your system.

## Installation

### Linux/Mac

Clone the repository:
```bash
git clone https://github.com/lbryio/lbry-sdk.git
cd lbry-sdk
```

Create a Python virtual environment for lbry-sdk:
```bash
python3.7 -m venv lbry-venv
```

Activate virtual environment:
```bash
source lbry-venv/bin/activate
```

Make sure you're on Python 3.7+ as default in the virtual environment:
```bash
python --version
```

Install packages:
```bash
make install
```

If you are on Linux and using PyCharm, generates initial configs:
```bash
make idea
```

To verify your installation, `which lbrynet` should return a path inside
of the `lbry-venv` folder.
```bash
(lbry-venv) $ which lbrynet
/opt/lbry-sdk/lbry-venv/bin/lbrynet
```

To exit the virtual environment simply use the command `deactivate`.

### Windows

Clone the repository:
```bash
git clone https://github.com/lbryio/lbry-sdk.git
cd lbry-sdk
```

Create a Python virtual environment for lbry-sdk:
```bash
python -m venv lbry-venv
```

Activate virtual environment:
```bash
lbry-venv\Scripts\activate
```

Install packages:
```bash
pip install -e .
```

## Run the tests
### Elasticsearch

For running integration tests, Elasticsearch is required to be available at localhost:9200/

The easiest way to start it is using docker with:
```bash
make elastic-docker
```

Alternative installation methods are available [at Elasticsearch website](https://www.elastic.co/guide/en/elasticsearch/reference/current/install-elasticsearch.html).

To run the unit and integration tests from the repo directory:
```
python -m unittest discover tests.unit
python -m unittest discover tests.integration
```

## Usage

To start the API server:
```
lbrynet start
```

Whenever the code inside [lbry-sdk/lbry](./lbry)
is modified we should run `make install` to recompile the `lbrynet`
executable with the newest code.

## Development

When developing, remember to enter the environment,
and if you wish start the server interactively.
```bash
$ source lbry-venv/bin/activate

(lbry-venv) $ python lbry/extras/cli.py start
```

Parameters can be passed in the same way.
```bash
(lbry-venv) $ python lbry/extras/cli.py wallet balance
```

If a Python debugger (`pdb` or `ipdb`) is installed we can also start it
in this way, set up break points, and step through the code.
```bash
(lbry-venv) $ pip install ipdb

(lbry-venv) $ ipdb lbry/extras/cli.py
```

Happy hacking!
