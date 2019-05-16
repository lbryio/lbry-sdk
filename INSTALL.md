# Installing LBRY

If only the JSON-RPC API server is needed, the recommended way to install LBRY is to use a pre-built binary. We provide binaries for all major operating systems. See the [README](README.md).

These instructions are for installing LBRY from source, which is recommended if you are interested in doing development work or LBRY is not available on your operating system (godspeed, TempleOS users).

Here's a video walkthrough of this setup, which is itself hosted by the LBRY network and provided via [spee.ch](https://github.com/lbryio/spee.ch):
[![Setup for development](https://spee.ch/2018-10-04-17-13-54-017046806.png)](https://spee.ch/967f99344308f1e90f0620d91b6c93e4dfb240e0/lbrynet-dev-setup.mp4)

## Prerequisites

Running `lbrynet` from source requires Python 3.6 or higher (3.7 is preferred). Get the installer for your OS [here](https://www.python.org/downloads/release/python-370/)

After installing python 3, you'll need to install some additional libraries depending on your operating system.

### macOS

macOS users will need to install [xcode command line tools](https://developer.xamarin.com/guides/testcloud/calabash/configuring/osx/install-xcode-command-line-tools/) and [homebrew](http://brew.sh/).

These environment variables also need to be set
1. PYTHONUNBUFFERED=1
2. EVENT_NOKQUEUE=1

Remaining dependencies can then be installed by running:

```
brew install python protobuf
```

Assistance installing Python3: https://docs.python-guide.org/starting/install3/osx/

### Linux

On Ubuntu (we recommend 18.04), install the following:

```
sudo apt-get install build-essential python3.7 python3.7-dev git python3-venv libssl-dev python-protobuf
```

On Raspbian, you will also need to install `python-pyparsing`.

If you're running another Linux distro, install the equivalent of the above packages for your system.

## Installation

To install:

 ```
 git clone https://github.com/lbryio/lbry.git
 cd lbry

 Creating venv:
 python -m venv lbry-venv
 
 Activating lbry-venv on Linux/Mac:
 source lbry-venv/bin/activate
 
 Activating lbry-venv on Windows: 
 lbry-venv\Scripts\activate

 python --version # Python 2 is not supported. Make sure you're on Python 3.7

 pip install -e .
 ```

To verify your installation, `which lbrynet` should return a path inside of the `lbry-venv` folder created by the `virtualenv` command.

## Run the tests
To run the unit tests from the repo directory:
 ```
 trial --reactor=asyncio tests.unit
 ```

## Usage

To start the API server:
    `lbrynet start`


Happy hacking!
