# <img src="https://raw.githubusercontent.com/lbryio/lbry/master/lbry.png" alt="LBRY" width="48" height="36" /> LBRY [![Build Status](https://travis-ci.org/lbryio/lbry.svg?branch=master)](https://travis-ci.org/lbryio/lbry) [![Test Coverage](https://codecov.io/gh/lbryio/lbry/branch/master/graph/badge.svg)](https://codecov.io/gh/lbryio/lbry)

LBRY is an open-source protocol providing distribution, discovery, and purchase of digital content (data) via a decentralized network. It utilizes the [LBRY blockchain](https://github.com/lbryio/lbrycrd) as a global namespace and database of digital content. Blockchain entries contain searchable content metadata, identities, and rights and access rules. LBRY also provides a data network that consists of peers uploading and downloading data from other peers, possibly in exchange for payments, and a distributed hash table, used by peers to discover other peers.

This project aims to provide a daemon that can interact with the network via a json-rpc interface over HTTP.

The project is written in Python 3.7+ and extensively uses Twisted framework.

## Installation

Our [releases page](https://github.com/lbryio/lbry/releases) contains pre-built binaries of the latest release, pre-releases, and past releases, for macOS, Debian-based Linux, and Windows. [Automated travis builds](http://build.lbry.io/daemon/) are also available for testing.

## Usage

Run `lbrynet start` to launch the daemon.

By default, `lbrynet` will provide a JSON-RPC server at `http://localhost:5279`. It is easy to interact with via cURL or sane programming languages.

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

The primary contact for this project is [@jackrobison](mailto:jack@lbry.io)

## Additional information and links

The documentation for the api can be found [here](https://lbry.io/api).
