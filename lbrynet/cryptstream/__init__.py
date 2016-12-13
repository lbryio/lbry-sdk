"""
Classes and functions for dealing with Crypt Streams.

Crypt Streams are encrypted blobs and metadata tying those blobs together. At least some of the
metadata is generally stored in a Stream Descriptor File, for example containing a public key
used to bind blobs to the stream and a symmetric key used to encrypt the blobs. The list of blobs
may or may not be present.
"""
