from __future__ import print_function
from .error import DecodeError
import sys
if sys.version_info > (3,):
    long = int

class Encoding(object):
    """ Interface for RPC message encoders/decoders

    All encoding implementations used with this library should inherit and
    implement this.
    """

    def encode(self, data):
        """ Encode the specified data

        @param data: The data to encode
                     This method has to support encoding of the following
                     types: C{str}, C{int} and C{long}
                     Any additional data types may be supported as long as the
                     implementing class's C{decode()} method can successfully
                     decode them.

        @return: The encoded data
        @rtype: str
        """

    def decode(self, data):
        """ Decode the specified data string

        @param data: The data (byte string) to decode.
        @type data: str

        @return: The decoded data (in its correct type)
        """


class Bencode(Encoding):
    """ Implementation of a Bencode-based algorithm (Bencode is the encoding
    algorithm used by Bittorrent).

    @note: This algorithm differs from the "official" Bencode algorithm in
           that it can encode/decode floating point values in addition to
           integers.
    """

    def encode(self, data):
        """ Encoder implementation of the Bencode algorithm

        @param data: The data to encode
        @type data: int, long, tuple, list, dict or str

        @return: The encoded data
        @rtype: str
        """
        if isinstance(data, (int, long)):
            return b'i%de' % data
        elif isinstance(data, str):
            return b'%d:%s' % (len(data), data.encode())
        elif isinstance(data, bytes):
            return b'%d:%s' % (len(data), data)
        elif isinstance(data, (list, tuple)):
            encodedListItems = b''
            for item in data:
                encodedListItems += self.encode(item)
            return b'l%se' % encodedListItems
        elif isinstance(data, dict):
            encodedDictItems = b''
            keys = data.keys()
            for key in sorted(keys):
                encodedDictItems += self.encode(key)  # TODO: keys should always be bytestrings
                encodedDictItems += self.encode(data[key])
            return b'd%se' % encodedDictItems
        else:
            raise TypeError("Cannot bencode '%s' object" % type(data))

    def decode(self, data):
        """ Decoder implementation of the Bencode algorithm

        @param data: The encoded data
        @type data: str

        @note: This is a convenience wrapper for the recursive decoding
               algorithm, C{_decodeRecursive}

        @return: The decoded data, as a native Python type
        @rtype:  int, list, dict or str
        """
        assert type(data) == bytes
        if len(data) == 0:
            raise DecodeError('Cannot decode empty string')
        try:
            return self._decodeRecursive(data)[0]
        except ValueError as e:
            raise DecodeError(e.message)

    @staticmethod
    def _decodeRecursive(data, startIndex=0):
        """ Actual implementation of the recursive Bencode algorithm

        Do not call this; use C{decode()} instead
        """
        if data[startIndex] == ord('i'):
            endPos = data[startIndex:].find(b'e') + startIndex
            return int(data[startIndex + 1:endPos]), endPos + 1
        elif data[startIndex] == ord('l'):
            startIndex += 1
            decodedList = []
            while data[startIndex] != ord('e'):
                listData, startIndex = Bencode._decodeRecursive(data, startIndex)
                decodedList.append(listData)
            return decodedList, startIndex + 1
        elif data[startIndex] == ord('d'):
            startIndex += 1
            decodedDict = {}
            while data[startIndex] != ord('e'):
                key, startIndex = Bencode._decodeRecursive(data, startIndex)
                value, startIndex = Bencode._decodeRecursive(data, startIndex)
                decodedDict[key] = value
            return decodedDict, startIndex
        elif data[startIndex] == ord('f'):
            # This (float data type) is a non-standard extension to the original Bencode algorithm
            endPos = data[startIndex:].find(ord('e')) + startIndex
            return float(data[startIndex + 1:endPos]), endPos + 1
        elif data[startIndex] == ord('n'):
            # This (None/NULL data type) is a non-standard extension
            # to the original Bencode algorithm
            return None, startIndex + 1
        else:
            splitPos = data[startIndex:].find(ord(':')) + startIndex
            try:
                length = int(data[startIndex:splitPos])
            except ValueError:
                raise DecodeError()
            startIndex = splitPos + 1
            endPos = startIndex + length
            bytes = data[startIndex:endPos]
            return bytes, endPos
