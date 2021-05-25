# Installing LBRY

If only the JSON-RPC API server is needed, the recommended way to install LBRY is to use a pre-built binary. We provide binaries for all major operating systems. See the [README](README.md)!

These instructions are for installing LBRY from source, which is recommended if you are interested in doing development work or LBRY is not available on your operating system (godspeed, TempleOS users).

Here's a video walkthrough of this setup, which is itself hosted by the LBRY network and provided via [spee.ch](https://github.com/lbryio/spee.ch):
[![Setup for development](https://spee.ch/2018-10-04-17-13-54-017046806.png)](https://spee.ch/967f99344308f1e90f0620d91b6c93e4dfb240e0/lbrynet-dev-setup.mp4)

## Prerequisites

Running `lbrynet` from source requires Python 3.7 or higher. Get the installer for your OS [here](https://www.python.org/downloads/release/python-370/).

After installing python 3, you'll need to install some additional libraries depending on your operating system.

### macOS

macOS users will need to install [xcode command line tools](https://developer.xamarin.com/guides/testcloud/calabash/configuring/osx/install-xcode-command-line-tools/) and [homebrew](http://brew.sh/).

These environment variables also need to be set:
1. PYTHONUNBUFFERED=1
2. EVENT_NOKQUEUE=1

Remaining dependencies can then be installed by running:

```
brew install python protobuf
```

Assistance installing Python3: https://docs.python-guide.org/starting/install3/osx/.

### Linux

On Ubuntu (16.04 minimum, we recommend 18.04), install the following:

```
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install build-essential python3.7 python3.7-dev git python3.7-venv libssl-dev python-protobuf
```

On Raspbian, you will also need to install `python-pyparsing`.

If you're running another Linux distro, install the equivalent of the above packages for your system.

## Installation

### Linux/Mac

To install on Linux/Mac:

 ```
 Clone the repository:
 $ git clone https://github.com/lbryio/lbry-sdk.git
 $ cd lbry-sdk

 Create a Python virtual environment for lbry-sdk:
 $ python3.7 -m venv lbry-venv
 
 Activating lbry-sdk virtual environment:
 $ source lbry-venv/bin/activate
 
 Make sure you're on Python 3.7+ (as the default Python in virtual environment):
 $ python --version

 Install packages:
 $ make install

 If you are on Linux and using PyCharm, generates initial configs:
 $ make idea
 ```

To verify your installation, `which lbrynet` should return a path inside of the `lbry-venv` folder created by the `python3.7 -m venv lbry-venv` command.

### Windows

To install on Windows:

 ```
 Clone the repository:
 > git clone https://github.com/lbryio/lbry-sdk.git
 > cd lbry-sdk

 Create a Python virtual environment for lbry-sdk:
 > python -m venv lbry-venv

 Activating lbry-sdk virtual environment:
 > lbry-venv\Scripts\activate

 Install packages:
 > pip install -e .
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
    `lbrynet start`


Happy hacking!
