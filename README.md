[![Build Status](https://travis-ci.org/lbryio/lbry.svg?branch=master)](https://travis-ci.org/lbryio/lbry)
[![Coverage Status](https://coveralls.io/repos/github/lbryio/lbry/badge.svg)](https://coveralls.io/github/lbryio/lbry)

# LBRY

LBRY is an open-source protocol providing distribution, discovery, and purchase of digital content (data) via a decentralized network.

This repo is a reference implementation of the [LBRY API](https://lbry.io/api). 

It provides a daemon that can interact with the network via a json-rpc interface over HTTP.

## Installing

**Note**: This project no longer directly bundles a graphic interface (browser). If you want to use LBRY via a browser, [use the LBRY App](https://github.com/lbryio/lbry-app).

Our [releases page](https://github.com/lbryio/lbry-app/releases/latest) contains pre-built binaries of the latest release, pre-releases, and past releases, for macOS, Debian-based Linux, and Windows.

Installing from source is also relatively painless, full instructions are in [INSTALL.md](INSTALL.md)

## Running

Run `lbrynet-daemon` to launch the daemon.

## Using

By default, `lbrynet-daemon` will provide a JSON-RPC server at `http://localhost:5279`. It is easy to interact with via cURL or sane programming languages.

Our [quickstart guide](http://lbry.io/quickstart) provides clear sample usages and free credits for learning.

The full API is documented [here](https://lbry.io/api).

## What is LBRY?

LBRY is a fully decentralized network for distributing data. It consists of peers uploading
and downloading data from other peers, possibly in exchange for payments, and a distributed hash
table, used by peers to discover other peers.

On LBRY, data is broken into chunks, and each chunk is content
addressable, specified by its sha384 hash sum. This guarantees that
peers can verify the correctness of each chunk without having to know
anything about its contents, and can confidently re-transmit the chunk
to other peers. Peers wishing to transmit chunks to other peers
announce to the distributed hash table that they are associated with
the sha384 hash sum in question. When a peer wants to download that
chunk from the network, it asks the distributed hash table which peers
are associated with that sha384 hash sum. The distributed hash table
can also be used more generally. It simply stores IP addresses and
ports which are associated with 384-bit numbers, and can be used by
any type of application to help peers find each other. For example, an
application for which clients don't know all of the necessary chunks
may use some identifier, chosen by the application, to find clients
which do know all of the necessary chunks.

## Contributions

To contribute, [join us on Slack](https://slack.lbry.io/) or contact jeremy@lbry.io. Pull requests are also welcome.

## Support

Please open an issue and describe your situation in detail. We will respond as soon as we can.

For private issues, contact jeremy@lbry.io.

## License

See [LICENSE](LICENSE)
