import typing
from lbrynet.dht.error import DecodeError


def _bencode(data: typing.Union[int, bytes, bytearray, str, list, tuple, dict]) -> bytes:
    if isinstance(data, int):
        return b'i%de' % data
    elif isinstance(data, (bytes, bytearray)):
        return b'%d:%s' % (len(data), data)
    elif isinstance(data, str):
        return b'%d:%s' % (len(data), data.encode())
    elif isinstance(data, (list, tuple)):
        encoded_list_items = b''
        for item in data:
            encoded_list_items += _bencode(item)
        return b'l%se' % encoded_list_items
    elif isinstance(data, dict):
        encoded_dict_items = b''
        keys = data.keys()
        for key in sorted(keys):
            encoded_dict_items += _bencode(key)
            encoded_dict_items += _bencode(data[key])
        return b'd%se' % encoded_dict_items
    else:
        raise TypeError(f"Cannot bencode {type(data)}")


def _bdecode(data: bytes, start_index: int = 0) -> typing.Tuple[typing.Union[int, bytes, list, tuple, dict], int]:
    if data[start_index] == ord('i'):
        end_pos = data[start_index:].find(b'e') + start_index
        return int(data[start_index + 1:end_pos]), end_pos + 1
    elif data[start_index] == ord('l'):
        start_index += 1
        decoded_list = []
        while data[start_index] != ord('e'):
            list_data, start_index = _bdecode(data, start_index)
            decoded_list.append(list_data)
        return decoded_list, start_index + 1
    elif data[start_index] == ord('d'):
        start_index += 1
        decoded_dict = {}
        while data[start_index] != ord('e'):
            key, start_index = _bdecode(data, start_index)
            value, start_index = _bdecode(data, start_index)
            decoded_dict[key] = value
        return decoded_dict, start_index
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


def bencode(data: dict) -> bytes:
    if not isinstance(data, dict):
        raise TypeError
    return _bencode(data)


def bdecode(data: bytes, allow_non_dict_return: typing.Optional[bool] = False) -> dict:
    """ Decoder implementation of the Bencode algorithm. """
    assert type(data) == bytes  # fixme: _maybe_ remove this after porting
    if len(data) == 0:
        raise DecodeError('Cannot decode empty string')
    try:
        result = _bdecode(data)[0]
        if not allow_non_dict_return and not isinstance(result, dict):
            raise ValueError(f'expected dict, got {type(result)}')
        return result
    except ValueError as e:
        raise DecodeError(str(e))
