[![Build Status](https://travis-ci.org/lbryio/lbry.svg?branch=master)](https://travis-ci.org/lbryio/lbry)
[![Coverage Status](https://coveralls.io/repos/github/lbryio/lbry/badge.svg)](https://coveralls.io/github/lbryio/lbry)

# LBRY

LBRY is an open-source protocol providing distribution, discovery, and purchase of digital content (data) via a decentralized network.

This repo is a reference implementation of the [LBRY API](https://lbry.io/api). 

It provides a daemon that can interact with the network via a json-rpc interface over HTTP.

## Installing

**Note**: This project no longer bundles a graphic interface (browser). If you want to use LBRY via a GUI, [use the LBRY App](https://github.com/lbryio/lbry-app).

Our [releases page](https://github.com/lbryio/lbry/releases) contains pre-built binaries of the latest release, pre-releases, and past releases, for macOS, Debian-based Linux, and Windows.

Installing from source is also relatively painless, full instructions are in [INSTALL.md](INSTALL.md)

## Running

Run `lbrynet-daemon` to launch the daemon.

## Using

By default, `lbrynet-daemon` will provide a JSON-RPC server at `http://localhost:5279`. It is easy to interact with via cURL or sane programming languages.

Our [quickstart guide](http://lbry.io/quickstart) provides a simple walkthrough and examples for learning.

The full API is documented [here](https://lbryio.github.io/lbry/cli).

## What is LBRY?

LBRY is a protocol that provides a fully decentralized network for the discovery, distribution, and payment of data. 

It utilizes the [LBRY blockchain](https://github.com/lbryio/lbrycrd) as a global namespace and database of digital content. Blockchain entries contain searchable content metadata, identities, and rights and access rules.

LBRY also provides a data network that consists of peers uploading and downloading data from other peers, possibly in exchange for payments, and a distributed hash table, used by peers to discover other peers.

## Contributions

To contribute, [join us on Discord](https://chat.lbry.io/) or contact jeremy@lbry.io. Pull requests are also welcome.

## Support

Please open an issue and describe your situation in detail. We will respond as soon as we can.

For private issues, contact jeremy@lbry.io.

## License

See [LICENSE](LICENSE)
