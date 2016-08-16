#!/usr/bin/env python
#
# This is a basic single-node example of how to use the Entangled DHT. It creates a Node and (optionally) joins an existing DHT.
# It then does a Kademlia store and find, and then it deletes the stored value (non-Kademlia method).
#
# No tuple space functionality is demonstrated by this script.
# 
# To test it properly, start a multi-node Kademlia DHT with the "create_network.py" 
# script and point this node to that, e.g.:
# $python create_network.py 10 127.0.0.1
# 
# $python basic_example.py 5000 127.0.0.1 4000
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive
#

# Thanks to Paul Cannon for IP-address resolution functions (taken from aspn.activestate.com)



import sys, hashlib, random
import twisted.internet.reactor
from lbrynet.dht.node import Node
#from entangled.kademlia.datastore import SQLiteDataStore

# The Entangled DHT node; instantiated in the main() method
node = None

# The key to use for this example when storing/retrieving data
hash = hashlib.sha384()
hash.update("key")
KEY = hash.digest()
# The value to store
VALUE = random.randint(10000, 20000)
import binascii
lbryid = KEY


def storeValue(key, value):
    """ Stores the specified value in the DHT using the specified key """
    global node
    print '\nStoring value; Key: %s, Value: %s' % (key, value)
    # Store the value in the DHT. This method returns a Twisted Deferred result, which we then add callbacks to
    deferredResult = node.announceHaveHash(key, value)
    # Add our callback; this method is called when the operation completes...
    deferredResult.addCallback(storeValueCallback)
    # ...and for error handling, add an "error callback" as well.
    # For this example script, I use a generic error handler; usually you would need something more specific
    deferredResult.addErrback(genericErrorCallback)


def storeValueCallback(*args, **kwargs):
    """ Callback function that is invoked when the storeValue() operation succeeds """
    print 'Value has been stored in the DHT'
    # Now that the value has been stored, schedule that the value is read again after 2.5 seconds
    print 'Scheduling retrieval in 2.5 seconds...'
    twisted.internet.reactor.callLater(2.5, getValue)


def genericErrorCallback(failure):
    """ Callback function that is invoked if an error occurs during any of the DHT operations """
    print 'An error has occurred:', failure.getErrorMessage()
    twisted.internet.reactor.callLater(0, stop)

def getValue():
    """ Retrieves the value of the specified key (KEY) from the DHT """
    global node, KEY
    # Get the value for the specified key (immediately returns a Twisted deferred result)
    print '\nRetrieving value from DHT for key "%s"...' % binascii.unhexlify("f7d9dc4de674eaa2c5a022eb95bc0d33ec2e75c6")
    deferredResult = node.iterativeFindValue(binascii.unhexlify("f7d9dc4de674eaa2c5a022eb95bc0d33ec2e75c6"))
    #deferredResult = node.iterativeFindValue(KEY)
    # Add a callback to this result; this will be called as soon as the operation has completed
    deferredResult.addCallback(getValueCallback)
    # As before, add the generic error callback
    deferredResult.addErrback(genericErrorCallback)


def getValueCallback(result):
    """ Callback function that is invoked when the getValue() operation succeeds """
    # Check if the key was found (result is a dict of format {key: value}) or not (in which case a list of "closest" Kademlia contacts would be returned instead")
    print "Got the value"
    print result
    #if type(result) == dict:
    #    for v in result[binascii.unhexlify("5292fa9c426621f02419f5050900392bdff5036c")]:
    #        print "v:", v
    #        print "v[6:", v[6:]
    #        print "lbryid:",lbryid
    #        print "lbryid == v[6:]:", lbryid == v[6:]
    #    print 'Value successfully retrieved: %s' % result[KEY]

    #else:
    #    print 'Value not found'
    # Either way, schedule a "delete" operation for the key
    #print 'Scheduling removal in 2.5 seconds...'
    #twisted.internet.reactor.callLater(2.5, deleteValue)
    print 'Scheduling shutdown in 2.5 seconds...'
    twisted.internet.reactor.callLater(2.5, stop)


def stop():
    """ Stops the Twisted reactor, and thus the script """
    print '\nStopping Kademlia node and terminating script...'
    twisted.internet.reactor.stop()

if __name__ == '__main__':
    
    import sys
    if len(sys.argv) < 2:
        print 'Usage:\n%s UDP_PORT [KNOWN_NODE_IP  KNOWN_NODE_PORT]' % sys.argv[0]
        print 'or:\n%s UDP_PORT [FILE_WITH_KNOWN_NODES]' % sys.argv[0]
        print '\nIf a file is specified, it should containg one IP address and UDP port\nper line, seperated by a space.'
        sys.exit(1)
    try:
        int(sys.argv[1])
    except ValueError:
        print '\nUDP_PORT must be an integer value.\n'
        print 'Usage:\n%s UDP_PORT  [KNOWN_NODE_IP  KNOWN_NODE_PORT]' % sys.argv[0]
        print 'or:\n%s UDP_PORT  [FILE_WITH_KNOWN_NODES]' % sys.argv[0]
        print '\nIf a file is specified, it should contain one IP address and UDP port\nper line, seperated by a space.'
        sys.exit(1)

    if len(sys.argv) == 4:
        knownNodes = [(sys.argv[2], int(sys.argv[3]))]
    elif len(sys.argv) == 3:
        knownNodes = []
        f = open(sys.argv[2], 'r')
        lines = f.readlines()
        f.close()
        for line in lines:
            ipAddress, udpPort = line.split()
            knownNodes.append((ipAddress, int(udpPort)))
    else:
        knownNodes = None
        print '\nNOTE: You have not specified any remote DHT node(s) to connect to'
        print 'It will thus not be aware of any existing DHT, but will still function as a self-contained DHT (until another node contacts it).'
        print 'Run this script without any arguments for info.\n'

    # Set up SQLite-based data store (you could use an in-memory store instead, for example)
    #if os.path.isfile('/tmp/dbFile%s.db' % sys.argv[1]):
    #    os.remove('/tmp/dbFile%s.db' % sys.argv[1])
    #dataStore = SQLiteDataStore(dbFile = '/tmp/dbFile%s.db' % sys.argv[1])
    # Create the Entangled node. It extends the functionality of a basic Kademlia node (but is fully backwards-compatible with a Kademlia-only network)
    # If you wish to have a pure Kademlia network, use the entangled.kademlia.node.Node class instead
    print 'Creating Node...'
    #node = EntangledNode( udpPort=int(sys.argv[1]), dataStore=dataStore )
    node = Node( udpPort=int(sys.argv[1]), lbryid=lbryid)

    # Schedule the node to join the Kademlia/Entangled DHT 
    node.joinNetwork(knownNodes)
    # Schedule the "storeValue() call to be invoked after 2.5 seconds, using KEY and VALUE as arguments
    #twisted.internet.reactor.callLater(2.5, storeValue, KEY, VALUE)
    twisted.internet.reactor.callLater(2.5, getValue)
    # Start the Twisted reactor - this fires up all networking, and allows the scheduled join operation to take place
    print 'Twisted reactor started (script will commence in 2.5 seconds)'
    twisted.internet.reactor.run()

