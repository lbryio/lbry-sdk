# LBRYnet

LBRYnet is a fully decentralized network for distributing data. It consists of peers uploading
and downloading data from other peers, possibly in exchange for payments, and a distributed hash
table, used by peers to discover other peers.

## Overview

On LBRYnet, data is broken into chunks, and each chunk is specified by its sha384 hash sum. This
guarantees that peers can verify the correctness of each chunk without having to know anything
about its contents, and can confidently re-transmit the chunk to other peers. Peers wishing to
transmit chunks to other peers announce to the distributed hash table that they are associated
with the sha384 hash sum in question. When a peer wants to download that chunk from the network,
it asks the distributed hash table which peers are associated with that sha384 hash sum. The
distributed hash table can also be used more generally. It simply stores IP addresses and
ports which are associated with 384-bit numbers, and can be used by any type of application to
help peers find each other. For example, an application for which clients don't know all of the
necessary chunks may use some identifier, chosen by the application, to find clients which do
know all of the necessary chunks.

## Running

LBRYnet comes with an file sharing application, called 'lbrynet-console', which breaks
files into chunks, encrypts them with a symmetric key, computes their sha384 hash sum, generates
a special file called a 'stream descriptor' containing the hash sums and some other file metadata,
and makes the chunks available for download by other peers. A peer wishing to download the file
must first obtain the 'stream descriptor' and then may open it with his 'lbrynet-console' client,
download all of the chunks by locating peers with the chunks via the DHT, and then combine the
chunks into the original file, according to the metadata included in the 'stream descriptor'.

To install and use this client, see [INSTALL](INSTALL.md) and [RUNNING](RUNNING.md)

## Installation

See [INSTALL](INSTALL.md)

## Developers

Documentation: doc.lbry.io
Source code: trac.lbry.io/browser

To contribute to the development of LBRYnet or lbrynet-console, contact jimmy@lbry.io

## Support

Send all support requests to jimmy@lbry.io

## License

See [LICENSE](LICENSE.md)
