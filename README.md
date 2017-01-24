[![Build Status](https://travis-ci.org/lbryio/lbry.svg?branch=master)](https://travis-ci.org/lbryio/lbry)
[![Coverage Status](https://coveralls.io/repos/github/lbryio/lbry/badge.svg)](https://coveralls.io/github/lbryio/lbry)

# LBRY

LBRY is a fully decentralized, open-source protocol facilitating the discovery, access, and (sometimes) purchase of data.

## Installing LBRY

We provide binaries for Windows, macOS, and Debian-based Linux.

| Windows | macOS | Linux |
| --- | --- | --- |
| [Download MSI](https://lbry.io/get/lbry.msi) | [Download DMG](https://lbry.io/get/lbry.dmg) | [Download DEB](https://lbry.io/get/lbry.deb) |

Our [releases page](https://github.com/lbryio/lbry/releases/latest) also contains the latest release, pre-releases, and past builds.

For instructions on building from source, see [INSTALL.md](INSTALL.md).

## What is LBRY?

LBRY is a fully decentralized network for distributing data. It consists of peers uploading
and downloading data from other peers, possibly in exchange for payments, and a distributed hash
table, used by peers to discover other peers.

On LBRY, data is broken into chunks, and each chunk is specified by its sha384 hash sum. This
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

The bundled LBRY application uses the lbrynet JSONRPC api found in `lbrynet.lbrynet_daemon.LBRYDaemon`. This api allows for applications and web services like the lbry browser UI to interact with lbrynet. If you've installed lbrynet, you can run `lbrynet-daemon` without running the app. While the app or `lbrynet-daemon` is running, you can use the following to show the help for all the available commands:

```
from jsonrpc.proxy import JSONRPCProxy

try:
  from lbrynet.conf import API_CONNECTION_STRING
except:
  print "You don't have lbrynet installed!"
  API_CONNECTION_STRING = "http://localhost:5279/lbryapi"
  
api = JSONRPCProxy.from_url(API_CONNECTION_STRING)
status = api.status()
if not status['is_running']:
      print status
else:
    for cmd in api.commands():
        print "%s:\n%s" % (cmd, api.help({'command': cmd}))
```

If you've installed lbrynet, it comes with a file sharing application, called `lbrynet-daemon`, which breaks
files into chunks, encrypts them with a symmetric key, computes their sha384 hash sum, generates
a special file called a 'stream descriptor' containing the hash sums and some other file metadata,
and makes the chunks available for download by other peers. A peer wishing to download the file
must first obtain the 'stream descriptor' and then may open it with his `lbrynet-daemon` client,
download all of the chunks by locating peers with the chunks via the DHT, and then combine the
chunks into the original file, according to the metadata included in the 'stream descriptor'.

For instructions on installing from source, see [INSTALL.md](INSTALL.md).

Source code: https://github.com/lbryio/lbry

To contribute, [join us on Slack](https://lbry-slackin.herokuapp.com/) or contact jeremy@lbry.io. Pull requests are also welcome.

## Support

Please open an issue and describe your situation in detail. We will respond as soon as we can.

For private issues, contact jeremy@lbry.io.

## License

See [LICENSE](LICENSE)
