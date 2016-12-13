"""
A client library for sending and receiving payments on the point trader network.

The point trader network is a simple payment system used solely for testing lbrynet-console. A user
creates a public key, registers it with the point trader server, and receives free points for
registering. The public key is used to spend points, and also used as an address to which points
are sent. To spend points, the public key signs a message containing the amount and the destination
public key and sends it to the point trader server. To check for payments, the recipient sends a
signed message asking the point trader server for its balance.
"""
