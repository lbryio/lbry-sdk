import six
import struct
import binascii
from torba.hash import double_sha256


class InvalidProofError(Exception):
    pass


def get_hash_for_outpoint(txhash, nout, height_of_last_takeover):
    return double_sha256(
        double_sha256(txhash) +
        double_sha256(str(nout).encode()) +
        double_sha256(struct.pack('>Q', height_of_last_takeover))
    )


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

        previous_computed_hash = double_sha256(to_hash)

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
