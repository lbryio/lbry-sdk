import six
import binascii

from lbryschema.hashing import sha256


class InvalidProofError(Exception):
    pass


def height_to_vch(n):
    r = [0 for i in range(8)]
    r[4] = n >> 24
    r[5] = n >> 16
    r[6] = n >> 8
    r[7] = n % 256
    # need to reset each value mod 256 because for values like 67784
    # 67784 >> 8 = 264, which is obviously larger then the maximum
    # value input into chr()
    return b''.join([six.int2byte(x % 256) for x in r])


def get_hash_for_outpoint(txhash, nOut, nHeightOfLastTakeover):
    txhash_hash = Hash(txhash)
    nOut_hash = Hash(str(nOut))
    height_of_last_takeover_hash = Hash(height_to_vch(nHeightOfLastTakeover))
    outPointHash = Hash(txhash_hash + nOut_hash + height_of_last_takeover_hash)
    return outPointHash


# noinspection PyPep8
def verify_proof(proof, rootHash, name):
    previous_computed_hash = None
    reverse_computed_name = ''
    verified_value = False
    for i, node in enumerate(proof['nodes'][::-1]):
        found_child_in_chain = False
        to_hash = b''
        previous_child_character = None
        for child in node['children']:
            if child['character'] < 0 or child['character'] > 255:
                raise InvalidProofError("child character not int between 0 and 255")
            if previous_child_character:
                if previous_child_character >= child['character']:
                    raise InvalidProofError("children not in increasing order")
            previous_child_character = child['character']
            to_hash += six.int2byte(child['character'])
            if 'nodeHash' in child:
                if len(child['nodeHash']) != 64:
                    raise InvalidProofError("invalid child nodeHash")
                to_hash += binascii.unhexlify(child['nodeHash'])[::-1]
            else:
                if previous_computed_hash is None:
                    raise InvalidProofError("previous computed hash is None")
                if found_child_in_chain is True:
                    raise InvalidProofError("already found the next child in the chain")
                found_child_in_chain = True
                reverse_computed_name += chr(child['character'])
                to_hash += previous_computed_hash

        if not found_child_in_chain:
            if i != 0:
                raise InvalidProofError("did not find the alleged child")
        if i == 0 and 'txhash' in proof and 'nOut' in proof and 'last takeover height' in proof:
            if len(proof['txhash']) != 64:
                raise InvalidProofError("txhash was invalid: {}".format(proof['txhash']))
            if not isinstance(proof['nOut'], six.integer_types):
                raise InvalidProofError("nOut was invalid: {}".format(proof['nOut']))
            if not isinstance(proof['last takeover height'], six.integer_types):
                raise InvalidProofError(
                    'last takeover height was invalid: {}'.format(proof['last takeover height']))
            to_hash += get_hash_for_outpoint(
                binascii.unhexlify(proof['txhash'])[::-1],
                proof['nOut'],
                proof['last takeover height']
            )
            verified_value = True
        elif 'valueHash' in node:
            if len(node['valueHash']) != 64:
                raise InvalidProofError("valueHash was invalid")
            to_hash += binascii.unhexlify(node['valueHash'])[::-1]

        previous_computed_hash = Hash(to_hash)

    if previous_computed_hash != binascii.unhexlify(rootHash)[::-1]:
        raise InvalidProofError("computed hash does not match roothash")
    if 'txhash' in proof and 'nOut' in proof:
        if not verified_value:
            raise InvalidProofError("mismatch between proof claim and outcome")
    if 'txhash' in proof and 'nOut' in proof:
        if name != reverse_computed_name[::-1]:
            raise InvalidProofError("name did not match proof")
    if not name.startswith(reverse_computed_name[::-1]):
        raise InvalidProofError("name fragment does not match proof")
    return True

def Hash(x):
    if isinstance(x, six.text_type):
        x = x.encode('utf-8')
    return sha256(sha256(x))
