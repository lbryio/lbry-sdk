# <img src="https://raw.githubusercontent.com/lbryio/lbry-sdk/master/lbry.png" alt="LBRY" width="48" height="36" /> LBRY SDK [![build](https://github.com/lbryio/lbry-sdk/actions/workflows/main.yml/badge.svg)](https://github.com/lbryio/lbry-sdk/actions/workflows/main.yml) [![coverage](https://coveralls.io/repos/github/lbryio/lbry-sdk/badge.svg)](https://coveralls.io/github/lbryio/lbry-sdk) [![kandi X-Ray](https://kandi.openweaver.com/badges/xray.svg)](https://kandi.openweaver.com/python/lbryio/lbry-sdk) [![kandi Featured](https://kandi.openweaver.com/badges/featured.svg)](https://kandi.openweaver.com/collections/blockchain/python-blockchain)

LBRY is a decentralized peer-to-peer protocol for publishing and accessing digital content. It utilizes the [LBRY blockchain](https://github.com/lbryio/lbrycrd) as a global namespace and database of digital content. Blockchain entries contain searchable content metadata, identities, rights and access rules. LBRY also provides a data network that consists of peers (seeders) uploading and downloading data from other peers, possibly in exchange for payments, as well as a distributed hash table used by peers to discover other peers.

LBRY SDK for Python is currently the most fully featured implementation of the LBRY Network protocols and includes many useful components and tools for building decentralized applications. Primary features and components include:

 * Built on Python 3.7 and `asyncio`.
 * Kademlia DHT (Distributed Hash Table) implementation for finding peers to download from and announcing to peers what we have to host ([lbry.dht](https://github.com/lbryio/lbry-sdk/tree/master/lbry/dht)).
 * Blob exchange protocol for transferring encrypted blobs of content and negotiating payments ([lbry.blob_exchange](https://github.com/lbryio/lbry-sdk/tree/master/lbry/blob_exchange)).
 * Protobuf schema for encoding and decoding metadata stored on the blockchain ([lbry.schema](https://github.com/lbryio/lbry-sdk/tree/master/lbry/schema)).
 * Wallet implementation for the LBRY blockchain ([lbry.wallet](https://github.com/lbryio/lbry-sdk/tree/master/lbry/wallet)).
 * Daemon with a JSON-RPC API to ease building end user applications in any language and for automating various tasks ([lbry.extras.daemon](https://github.com/lbryio/lbry-sdk/tree/master/lbry/extras/daemon)). 

## Installation

Our [releases page](https://github.com/lbryio/lbry-sdk/releases) contains pre-built binaries of the latest release, pre-releases, and past releases for macOS, Debian-based Linux, and Windows. [Automated travis builds](http://build.lbry.io/daemon/) are also available for testing.

## Usage

Run `lbrynet start` to launch the API server.

By default, `lbrynet` will provide a JSON-RPC server at `http://localhost:5279`. It is easy to interact with via cURL or sane programming languages.

Our [quickstart guide](https://lbry.tech/playground) provides a simple walkthrough and examples for learning.

With the daemon running, `lbrynet commands` will show you a list of commands.

The full API is documented [here](https://lbry.tech/api/sdk).

## Running from source

Installing from source is also relatively painless. Full instructions are in [INSTALL.md](INSTALL.md)

## Contributing

Contributions to this project are welcome, encouraged, and compensated. For more details, please check [this](https://lbry.tech/contribute) link.

## License

This project is MIT licensed. For the full license, see [LICENSE](LICENSE).

## Security

We take security seriously. Please contact security@lbry.com regarding any security issues. [Our PGP key is here](https://lbry.com/faq/pgp-key) if you need it.

## Contact

The primary contact for this project is [@eukreign](mailto:lex@lbry.com).

## Additional information and links

The documentation for the API can be found [here](https://lbry.tech/api/sdk).

Daemon defaults, ports, and other settings are documented [here](https://lbry.tech/resources/daemon-settings).

Settings can be configured using a daemon-settings.yml file. An example can be found [here](https://github.com/lbryio/lbry-sdk/blob/master/example_daemon_settings.yml).
