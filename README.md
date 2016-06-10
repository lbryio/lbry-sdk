[![Build Status](https://travis-ci.org/lbryio/lbry.svg?branch=master)](https://travis-ci.org/lbryio/lbry)

# LBRYnet

LBRYnet is a fully decentralized network for distributing data. It consists of peers uploading
and downloading data from other peers, possibly in exchange for payments, and a distributed hash
table, used by peers to discover other peers.

## Installation

Download the [latest release](https://github.com/lbryio/lbry/releases/latest) or see [INSTALL.md](INSTALL.md) for manual installation.

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

## For Developers

The bundled LBRY application uses the JSONRPC api to LBRYnet found in `lbrynet.lbrynet_daemon.LBRYDaemon`. With a normal installation of the app, lbry command line is not available. To install lbrynet, see [INSTALL.md](INSTALL.md). The following uses the JSONRPC api to show the help for all the available commands:

```
from jsonrpc.proxy import JSONRPCProxy
from lbrynet.conf import API_CONNECTION_STRING
  
api = JSONRPCProxy.from_url(API_CONNECTION_STRING)
if not api.is_running():
  print api.daemon_status()
else:
  for func in api.help():
    print "%s:\n%s" % (func, api.help({'function': func}))
```

If you've installed lbrynet, it comes with a file sharing application, called `lbrynet-daemon`, which breaks
files into chunks, encrypts them with a symmetric key, computes their sha384 hash sum, generates
a special file called a 'stream descriptor' containing the hash sums and some other file metadata,
and makes the chunks available for download by other peers. A peer wishing to download the file
must first obtain the 'stream descriptor' and then may open it with his `lbrynet-daemon` client,
download all of the chunks by locating peers with the chunks via the DHT, and then combine the
chunks into the original file, according to the metadata included in the 'stream descriptor'.

For detailed instructions, see [INSTALL.md](INSTALL.md) and [RUNNING.md](RUNNING.md).

Documentation: doc.lbry.io (may be out of date)

Source code: https://github.com/lbryio/lbry

To contribute, [join us on Slack](https://lbry-slackin.herokuapp.com/) or contact josh@lbry.io. Pull requests are also welcome.

## Support

Please open an issue and describe your situation in detail. We will respond as soon as we can.

For private issues, contact josh@lbry.io.

## License

See [LICENSE](LICENSE)
