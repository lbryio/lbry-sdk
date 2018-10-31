# Installing LBRY

If only the json-rpc API server is needed, the recommended way to install LBRY is to use a pre-built binary. We provide binaries for all major operating systems. See the [README](README.md).

These instructions are for installing LBRY from source, which is recommended if you are interested in doing development work or LBRY is not available on your operating system (godspeed, TempleOS users).

Here's a video walkthrough of this setup which is itself hosted by the LBRY network and provided via [spee.ch](https://github.com/lbryio/spee.ch):
[![Setup for development](https://spee.ch/2018-10-04-17-13-54-017046806.png)](https://spee.ch/967f99344308f1e90f0620d91b6c93e4dfb240e0/lbrynet-dev-setup.mp4)

## Prerequisites

Running `lbrynet` from source requires Python 3.6 or higher (3.7 is preferred). Get the installer for your OS [here](https://www.python.org/downloads/release/python-370/)

After installing python 3 you'll need to install some additional libraries depending on your operating system.

### Virtualenv

Once python 3 is installed run `python3 -m pip install virtualenv` to install virtualenv.

### Windows

Windows users will need to install `Visual C++ Build Tools`, which can be installed by [Microsoft Build Tools](Microsoft Build Tools 2015)


### macOS

macOS users will need to install [xcode command line tools](https://developer.xamarin.com/guides/testcloud/calabash/configuring/osx/install-xcode-command-line-tools/) and [homebrew](http://brew.sh/).

Remaining dependencies can then be installed by running:

```
brew install python3 protobuf
```

### Linux

On Ubuntu (we recommend 18.04), install the following:

```
sudo apt-get install build-essential python3.7 python3.7-dev git python-virtualenv libssl-dev python-protobuf
```

On Raspbian, you will also need to install `python-pyparsing`.

If you're running another Linux flavor, install the equivalent of the above packages for your system.

## Installation

To install:

 ```
 git clone https://github.com/lbryio/lbry.git
 cd lbry
 
 virtualenv lbry-venv --python=python3.7
 source lbry-venv/bin/activate

 python --version # Python 2 is not supported. Make sure you're on Python 3.7

 pip install --editable .[test]  # [test] installs extras needed for running the tests
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
