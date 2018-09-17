class SignatureSerializationFlag:
    UNSIGNED = 0
    '''
    Format:
    <FLAG><CLAIM BINARY>
    or (legacy)
    <CLAIM BINARY>
    '''
    ECDSA_LEGACY = 1
    '''
    Old claim format, which carried the signature inside the protobuf. Requires serializing back the claim with
    signature stripped out for validation. This process requires knowledge on how a claim is serialized, thus requires
    old fixed protobuf schema to work.
    
    Format:
    <CLAIM PROTOBUF SERIALIZED>
    Curves: NIST256p, NIST384p, SECP256k1
    Signature content: `r` and `s` in each half of the 64 or 96 bytes (depends on curve)
    Signed payload:
    1. Claim transaction output address (raw, decoded using base58)
    2. Stripped out claim protobuf serialization (without the signature)
    3. Certificate claim id (binary, not in network byte order)
    '''
    ECDSA_SECP256K1 = 2
    '''
    Format:
    <FLAG><CERTIFICATE ID><SIGNATURE><BINARY PAYLOAD>
    Curve: SECP256K1
    Signature content: 64 bytes total, each half represents `r` and `s`
    Signed payload:
    1. raw claim name as bytes
    2. Claim transaction output address (raw, decoded using base58)
    3. Binary payload, independent of serialization (everything after the signature last byte)
    4. Certificate claim id, not in network byte order.
    
    A certificate can be signed as well, but this serialization model is unaware of content type or protobuf format.
    '''
    @classmethod
    def is_flag_valid(cls, flag):
        # todo: use python 3 enum when fully ported, but not worth now as its an extra dependency for py2
        return 0 <= flag <= 2