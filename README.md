# LBRY

[![Build Status](https://travis-ci.org/lbryio/lbry.svg?branch=master)](https://travis-ci.org/lbryio/lbry)
[![Coverage Status](https://coveralls.io/repos/github/lbryio/lbry/badge.svg)](https://coveralls.io/github/lbryio/lbry)

LBRY is an open-source protocol providing distribution, discovery, and purchase of digital content (data) via a decentralized network. It utilizes the [LBRY blockchain](https://github.com/lbryio/lbrycrd) as a global namespace and database of digital content. Blockchain entries contain searchable content metadata, identities, and rights and access rules. LBRY also provides a data network that consists of peers uploading and downloading data from other peers, possibly in exchange for payments, and a distributed hash table, used by peers to discover other peers.

This project aims to provide a daemon that can interact with the network via a json-rpc interface over HTTP.

The project is written in python2.7 and extensively uses Twisted framework.

## Installation

|                       | Windows                                      | macOS                                        | Linux                                        |
| --------------------- | -------------------------------------------- | -------------------------------------------- | -------------------------------------------- |
| Latest Stable Release | [Download](https://github.com/lbryio/lbry/releases/download/v0.20.0/lbrynet-daemon-v0.20.0-windows.zip)     | [Download](https://github.com/lbryio/lbry/releases/download/v0.20.0/lbrynet-daemon-v0.20.0-macos.zip)     | [Download](https://github.com/lbryio/lbry/releases/download/v0.20.0/lbrynet-daemon-v0.20.0-linux.zip)     |
| Latest Pre-release     | [Download](https://github.com/lbryio/lbry/releases/download/untagged-99114fa31abbfe3a5ef4/lbrynet-daemon-v0.20.1rc3-windows.zip) | [Download](https://github.com/lbryio/lbry/releases/download/untagged-99114fa31abbfe3a5ef4/lbrynet-daemon-v0.20.1rc3-macos.zip) | [Download](https://github.com/lbryio/lbry/releases/download/v0.20.1rc4/lbrynet-daemon-v0.20.1rc4-linux.zip) |

Our [releases page](https://github.com/lbryio/lbry/releases) contains pre-built binaries of the latest release, pre-releases, and past releases, for macOS, Debian-based Linux, and Windows.

## Usage

Run `lbrynet-daemon` to launch the daemon.

By default, `lbrynet-daemon` will provide a JSON-RPC server at `http://localhost:5279`. It is easy to interact with via cURL or sane programming languages.

Our [quickstart guide](http://lbry.io/quickstart) provides a simple walkthrough and examples for learning.

The full API is documented [here](https://lbryio.github.io/lbry/cli).

## Running from source

Installing from source is also relatively painless, full instructions are in [INSTALL.md](INSTALL.md)

## Contributing

Contributions to this project are welcome, encouraged, and compensated. For more details, please check [this](https://lbry.io/faq/contributing) link.

## License

This project is MIT licensed. For the full license, see [LICENSE](LICENSE).

## Security

We take security seriously. Please contact security@lbry.io regarding any security issues. Our PGP key is here if you need it.

## Contact

The primary contact for this project is @jackrobison(jack@lbry.io)

## Additional information and links

The documentation for the api can be found [here](https://lbry.io/api).