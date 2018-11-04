import struct
from torba.server.enum import Enumeration
from .model import NameClaim, ClaimSupport, ClaimUpdate
# TODO: Take this to lbryschema (it's also on lbryum and lbryum-server)


opcodes = Enumeration("Opcodes", [
    ("OP_0", 0), ("OP_PUSHDATA1", 76), "OP_PUSHDATA2", "OP_PUSHDATA4", "OP_1NEGATE", "OP_RESERVED",
    "OP_1", "OP_2", "OP_3", "OP_4", "OP_5", "OP_6", "OP_7",
    "OP_8", "OP_9", "OP_10", "OP_11", "OP_12", "OP_13", "OP_14", "OP_15", "OP_16",
    "OP_NOP", "OP_VER", "OP_IF", "OP_NOTIF", "OP_VERIF", "OP_VERNOTIF", "OP_ELSE", "OP_ENDIF",
    "OP_VERIFY",
    "OP_RETURN", "OP_TOALTSTACK", "OP_FROMALTSTACK", "OP_2DROP", "OP_2DUP", "OP_3DUP", "OP_2OVER",
    "OP_2ROT", "OP_2SWAP",
    "OP_IFDUP", "OP_DEPTH", "OP_DROP", "OP_DUP", "OP_NIP", "OP_OVER", "OP_PICK", "OP_ROLL",
    "OP_ROT",
    "OP_SWAP", "OP_TUCK", "OP_CAT", "OP_SUBSTR", "OP_LEFT", "OP_RIGHT", "OP_SIZE", "OP_INVERT",
    "OP_AND",
    "OP_OR", "OP_XOR", "OP_EQUAL", "OP_EQUALVERIFY", "OP_RESERVED1", "OP_RESERVED2", "OP_1ADD",
    "OP_1SUB", "OP_2MUL",
    "OP_2DIV", "OP_NEGATE", "OP_ABS", "OP_NOT", "OP_0NOTEQUAL", "OP_ADD", "OP_SUB", "OP_MUL",
    "OP_DIV",
    "OP_MOD", "OP_LSHIFT", "OP_RSHIFT", "OP_BOOLAND", "OP_BOOLOR",
    "OP_NUMEQUAL", "OP_NUMEQUALVERIFY", "OP_NUMNOTEQUAL", "OP_LESSTHAN",
    "OP_GREATERTHAN", "OP_LESSTHANOREQUAL", "OP_GREATERTHANOREQUAL", "OP_MIN", "OP_MAX",
    "OP_WITHIN", "OP_RIPEMD160", "OP_SHA1", "OP_SHA256", "OP_HASH160",
    "OP_HASH256", "OP_CODESEPARATOR", "OP_CHECKSIG", "OP_CHECKSIGVERIFY", "OP_CHECKMULTISIG",
    "OP_CHECKMULTISIGVERIFY", "OP_NOP1", "OP_NOP2", "OP_NOP3", "OP_NOP4", "OP_NOP5",
    "OP_CLAIM_NAME",
    "OP_SUPPORT_CLAIM", "OP_UPDATE_CLAIM",
    ("OP_SINGLEBYTE_END", 0xF0),
    ("OP_DOUBLEBYTE_BEGIN", 0xF000),
    "OP_PUBKEY", "OP_PUBKEYHASH",
    ("OP_INVALIDOPCODE", 0xFFFF),
])


def script_GetOp(bytes):
    i = 0
    while i < len(bytes):
        vch = None
        opcode = bytes[i]
        i += 1
        if opcode <= opcodes.OP_PUSHDATA4:
            nSize = opcode
            if opcode == opcodes.OP_PUSHDATA1:
                nSize = bytes[i]
                i += 1
            elif opcode == opcodes.OP_PUSHDATA2:
                (nSize,) = struct.unpack_from('<H', bytes, i)
                i += 2
            elif opcode == opcodes.OP_PUSHDATA4:
                (nSize,) = struct.unpack_from('<I', bytes, i)
                i += 4
            if i + nSize > len(bytes):
                vch = "_INVALID_" + bytes[i:]
                i = len(bytes)
            else:
                vch = bytes[i:i + nSize]
                i += nSize
        yield (opcode, vch, i)


def decode_claim_script(bytes_script):
    try:
        decoded_script = [x for x in script_GetOp(bytes_script)]
    except Exception as e:
        print(e)
        return None
    if len(decoded_script) <= 6:
        return False
    op = 0
    claim_type = decoded_script[op][0]
    if claim_type == opcodes.OP_UPDATE_CLAIM:
        if len(decoded_script) <= 7:
            return False
    if claim_type not in [
        opcodes.OP_CLAIM_NAME,
        opcodes.OP_SUPPORT_CLAIM,
        opcodes.OP_UPDATE_CLAIM
    ]:
        return False
    op += 1
    value = None
    claim_id = None
    claim = None
    if not (0 <= decoded_script[op][0] <= opcodes.OP_PUSHDATA4):
        return False
    name = decoded_script[op][1]
    op += 1
    if not (0 <= decoded_script[op][0] <= opcodes.OP_PUSHDATA4):
        return False
    if decoded_script[0][0] in [
        opcodes.OP_SUPPORT_CLAIM,
        opcodes.OP_UPDATE_CLAIM
    ]:
        claim_id = decoded_script[op][1]
        if len(claim_id) != 20:
            return False
    else:
        value = decoded_script[op][1]
    op += 1
    if decoded_script[0][0] == opcodes.OP_UPDATE_CLAIM:
        value = decoded_script[op][1]
        op += 1
    if decoded_script[op][0] != opcodes.OP_2DROP:
        return False
    op += 1
    if decoded_script[op][0] != opcodes.OP_DROP and decoded_script[0][0] == opcodes.OP_CLAIM_NAME:
        return False
    elif decoded_script[op][0] != opcodes.OP_2DROP and decoded_script[0][0] == opcodes.OP_UPDATE_CLAIM:
        return False
    op += 1
    if decoded_script[0][0] == opcodes.OP_CLAIM_NAME:
        if name is None or value is None:
            return False
        claim = NameClaim(name, value)
    elif decoded_script[0][0] == opcodes.OP_UPDATE_CLAIM:
        if name is None or value is None or claim_id is None:
            return False
        claim = ClaimUpdate(name, claim_id, value)
    elif decoded_script[0][0] == opcodes.OP_SUPPORT_CLAIM:
        if name is None or claim_id is None:
            return False
        claim = ClaimSupport(name, claim_id)
    return claim, decoded_script[op:]
