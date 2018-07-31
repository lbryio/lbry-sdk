from .error import DecodeError


def bencode(data):
    """ Encoder implementation of the Bencode algorithm (Bittorrent). """
    if isinstance(data, int):
        return b'i%de' % data
    elif isinstance(data, (bytes, bytearray)):
        return b'%d:%s' % (len(data), data)
    elif isinstance(data, str):
        return b'%d:%s' % (len(data), data.encode())
    elif isinstance(data, (list, tuple)):
        encoded_list_items = b''
        for item in data:
            encoded_list_items += bencode(item)
        return b'l%se' % encoded_list_items
    elif isinstance(data, dict):
        encoded_dict_items = b''
        keys = data.keys()
        for key in sorted(keys):
            encoded_dict_items += bencode(key)
            encoded_dict_items += bencode(data[key])
        return b'd%se' % encoded_dict_items
    else:
        raise TypeError("Cannot bencode '%s' object" % type(data))


def bdecode(data):
    """ Decoder implementation of the Bencode algorithm. """
    assert type(data) == bytes  # fixme: _maybe_ remove this after porting
    if len(data) == 0:
        raise DecodeError('Cannot decode empty string')
    try:
        return _decode_recursive(data)[0]
    except ValueError as e:
        raise DecodeError(str(e))


def _decode_recursive(data, start_index=0):
    if data[start_index] == ord('i'):
        end_pos = data[start_index:].find(b'e') + start_index
        return int(data[start_index + 1:end_pos]), end_pos + 1
    elif data[start_index] == ord('l'):
        start_index += 1
        decoded_list = []
        while data[start_index] != ord('e'):
            list_data, start_index = _decode_recursive(data, start_index)
            decoded_list.append(list_data)
        return decoded_list, start_index + 1
    elif data[start_index] == ord('d'):
        start_index += 1
        decoded_dict = {}
        while data[start_index] != ord('e'):
            key, start_index = _decode_recursive(data, start_index)
            value, start_index = _decode_recursive(data, start_index)
            decoded_dict[key] = value
        return decoded_dict, start_index
    elif data[start_index] == ord('f'):
        # This (float data type) is a non-standard extension to the original Bencode algorithm
        end_pos = data[start_index:].find(b'e') + start_index
        return float(data[start_index + 1:end_pos]), end_pos + 1
    elif data[start_index] == ord('n'):
        # This (None/NULL data type) is a non-standard extension
        # to the original Bencode algorithm
        return None, start_index + 1
    else:
        split_pos = data[start_index:].find(b':') + start_index
        try:
            length = int(data[start_index:split_pos])
        except ValueError:
            raise DecodeError()
        start_index = split_pos + 1
        end_pos = start_index + length
        b = data[start_index:end_pos]
        return b, end_pos
