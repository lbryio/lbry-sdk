[![Build Status](https://travis-ci.org/lbryio/lbry.svg?branch=master)](https://travis-ci.org/lbryio/lbry)
[![Coverage Status](https://coveralls.io/repos/github/lbryio/lbry/badge.svg)](https://coveralls.io/github/lbryio/lbry)

# LBRY

LBRY is a fully decentralized, open-source protocol facilitating the
discovery, access, and (sometimes) purchase of data.

This repo is a reference implementation of the LBRY protocol and
provides daemon that can interact with the network via a json-rpc
interface.

## Installing the LBRY App

The LBRY App is a decentralized content marketplace built on top of
the LBRY protocol. We provide binaries for Windows, macOS, and
Debian-based Linux.

| Windows | macOS | Linux |
| --- | --- | --- |
| [Download](https://lbry.io/get/lbry.msi) | [Download](https://lbry.io/get/lbry.dmg) | [Download](https://lbry.io/get/lbry.deb) |

Our [releases page](https://github.com/lbryio/lbry-app/releases/latest) also contains the latest release, pre-releases, and past builds.


## Using the LBRY daemon

See our quickstart guide at http://lbry.io/quickstart for details on how to install and use the `lbrynet-daemon`.


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

To contribute, [join us on Slack](https://lbry-slackin.herokuapp.com/) or contact jeremy@lbry.io. Pull requests are also welcome.

## Support

Please open an issue and describe your situation in detail. We will respond as soon as we can.

For private issues, contact jeremy@lbry.io.

## License

See [LICENSE](LICENSE)
