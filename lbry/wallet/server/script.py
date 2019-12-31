# Copyright (c) 2016-2017, Neil Booth
#
# All rights reserved.
#
# The MIT License (MIT)
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
# and warranty status of this software.

"""Script-related classes and functions."""


from collections import namedtuple

from lbry.wallet.server.util import unpack_le_uint16_from, unpack_le_uint32_from, \
    pack_le_uint16, pack_le_uint32


class EnumError(Exception):
    pass


class Enumeration:

    def __init__(self, name, enumList):
        self.__doc__ = name

        lookup = {}
        reverseLookup = {}
        i = 0
        uniqueNames = set()
        uniqueValues = set()
        for x in enumList:
            if isinstance(x, tuple):
                x, i = x
            if not isinstance(x, str):
                raise EnumError(f"enum name {x} not a string")
            if not isinstance(i, int):
                raise EnumError(f"enum value {i} not an integer")
            if x in uniqueNames:
                raise EnumError(f"enum name {x} not unique")
            if i in uniqueValues:
                raise EnumError(f"enum value {i} not unique")
            uniqueNames.add(x)
            uniqueValues.add(i)
            lookup[x] = i
            reverseLookup[i] = x
            i = i + 1
        self.lookup = lookup
        self.reverseLookup = reverseLookup

    def __getattr__(self, attr):
        result = self.lookup.get(attr)
        if result is None:
            raise AttributeError(f'enumeration has no member {attr}')
        return result

    def whatis(self, value):
        return self.reverseLookup[value]


class ScriptError(Exception):
    """Exception used for script errors."""


OpCodes = Enumeration("Opcodes", [
    ("OP_0", 0), ("OP_PUSHDATA1", 76),
    "OP_PUSHDATA2", "OP_PUSHDATA4", "OP_1NEGATE",
    "OP_RESERVED",
    "OP_1", "OP_2", "OP_3", "OP_4", "OP_5", "OP_6", "OP_7", "OP_8",
    "OP_9", "OP_10", "OP_11", "OP_12", "OP_13", "OP_14", "OP_15", "OP_16",
    "OP_NOP", "OP_VER", "OP_IF", "OP_NOTIF", "OP_VERIF", "OP_VERNOTIF",
    "OP_ELSE", "OP_ENDIF", "OP_VERIFY", "OP_RETURN",
    "OP_TOALTSTACK", "OP_FROMALTSTACK", "OP_2DROP", "OP_2DUP", "OP_3DUP",
    "OP_2OVER", "OP_2ROT", "OP_2SWAP", "OP_IFDUP", "OP_DEPTH", "OP_DROP",
    "OP_DUP", "OP_NIP", "OP_OVER", "OP_PICK", "OP_ROLL", "OP_ROT",
    "OP_SWAP", "OP_TUCK",
    "OP_CAT", "OP_SUBSTR", "OP_LEFT", "OP_RIGHT", "OP_SIZE",
    "OP_INVERT", "OP_AND", "OP_OR", "OP_XOR", "OP_EQUAL", "OP_EQUALVERIFY",
    "OP_RESERVED1", "OP_RESERVED2",
    "OP_1ADD", "OP_1SUB", "OP_2MUL", "OP_2DIV", "OP_NEGATE", "OP_ABS",
    "OP_NOT", "OP_0NOTEQUAL", "OP_ADD", "OP_SUB", "OP_MUL", "OP_DIV", "OP_MOD",
    "OP_LSHIFT", "OP_RSHIFT", "OP_BOOLAND", "OP_BOOLOR", "OP_NUMEQUAL",
    "OP_NUMEQUALVERIFY", "OP_NUMNOTEQUAL", "OP_LESSTHAN", "OP_GREATERTHAN",
    "OP_LESSTHANOREQUAL", "OP_GREATERTHANOREQUAL", "OP_MIN", "OP_MAX",
    "OP_WITHIN",
    "OP_RIPEMD160", "OP_SHA1", "OP_SHA256", "OP_HASH160", "OP_HASH256",
    "OP_CODESEPARATOR", "OP_CHECKSIG", "OP_CHECKSIGVERIFY", "OP_CHECKMULTISIG",
    "OP_CHECKMULTISIGVERIFY",
    "OP_NOP1",
    "OP_CHECKLOCKTIMEVERIFY", "OP_CHECKSEQUENCEVERIFY"
])


# Paranoia to make it hard to create bad scripts
assert OpCodes.OP_DUP == 0x76
assert OpCodes.OP_HASH160 == 0xa9
assert OpCodes.OP_EQUAL == 0x87
assert OpCodes.OP_EQUALVERIFY == 0x88
assert OpCodes.OP_CHECKSIG == 0xac
assert OpCodes.OP_CHECKMULTISIG == 0xae


def _match_ops(ops, pattern):
    if len(ops) != len(pattern):
        return False
    for op, pop in zip(ops, pattern):
        if pop != op:
            # -1 means 'data push', whose op is an (op, data) tuple
            if pop == -1 and isinstance(op, tuple):
                continue
            return False

    return True


class ScriptPubKey:
    """A class for handling a tx output script that gives conditions
    necessary for spending.
    """

    TO_ADDRESS_OPS = [OpCodes.OP_DUP, OpCodes.OP_HASH160, -1,
                      OpCodes.OP_EQUALVERIFY, OpCodes.OP_CHECKSIG]
    TO_P2SH_OPS = [OpCodes.OP_HASH160, -1, OpCodes.OP_EQUAL]
    TO_PUBKEY_OPS = [-1, OpCodes.OP_CHECKSIG]

    PayToHandlers = namedtuple('PayToHandlers', 'address script_hash pubkey '
                               'unspendable strange')

    @classmethod
    def pay_to(cls, handlers, script):
        """Parse a script, invoke the appropriate handler and
        return the result.

        One of the following handlers is invoked:
           handlers.address(hash160)
           handlers.script_hash(hash160)
           handlers.pubkey(pubkey)
           handlers.unspendable()
           handlers.strange(script)
        """
        try:
            ops = Script.get_ops(script)
        except ScriptError:
            return handlers.unspendable()

        match = _match_ops

        if match(ops, cls.TO_ADDRESS_OPS):
            return handlers.address(ops[2][-1])
        if match(ops, cls.TO_P2SH_OPS):
            return handlers.script_hash(ops[1][-1])
        if match(ops, cls.TO_PUBKEY_OPS):
            return handlers.pubkey(ops[0][-1])
        if ops and ops[0] == OpCodes.OP_RETURN:
            return handlers.unspendable()
        return handlers.strange(script)

    @classmethod
    def P2SH_script(cls, hash160):
        return (bytes([OpCodes.OP_HASH160])
                + Script.push_data(hash160)
                + bytes([OpCodes.OP_EQUAL]))

    @classmethod
    def P2PKH_script(cls, hash160):
        return (bytes([OpCodes.OP_DUP, OpCodes.OP_HASH160])
                + Script.push_data(hash160)
                + bytes([OpCodes.OP_EQUALVERIFY, OpCodes.OP_CHECKSIG]))

    @classmethod
    def validate_pubkey(cls, pubkey, req_compressed=False):
        if isinstance(pubkey, (bytes, bytearray)):
            if len(pubkey) == 33 and pubkey[0] in (2, 3):
                return  # Compressed
            if len(pubkey) == 65 and pubkey[0] == 4:
                if not req_compressed:
                    return
                raise PubKeyError('uncompressed pubkeys are invalid')
        raise PubKeyError(f'invalid pubkey {pubkey}')

    @classmethod
    def pubkey_script(cls, pubkey):
        cls.validate_pubkey(pubkey)
        return Script.push_data(pubkey) + bytes([OpCodes.OP_CHECKSIG])

    @classmethod
    def multisig_script(cls, m, pubkeys):
        """Returns the script for a pay-to-multisig transaction."""
        n = len(pubkeys)
        if not 1 <= m <= n <= 15:
            raise ScriptError(f'{m:d} of {n:d} multisig script not possible')
        for pubkey in pubkeys:
            cls.validate_pubkey(pubkey, req_compressed=True)
        # See https://bitcoin.org/en/developer-guide
        # 2 of 3 is: OP_2 pubkey1 pubkey2 pubkey3 OP_3 OP_CHECKMULTISIG
        return (bytes([OP_1 + m - 1])
                + b''.join(cls.push_data(pubkey) for pubkey in pubkeys)
                + bytes([OP_1 + n - 1, OP_CHECK_MULTISIG]))


class Script:

    @classmethod
    def get_ops(cls, script):
        ops = []

        # The unpacks or script[n] below throw on truncated scripts
        try:
            n = 0
            while n < len(script):
                op = script[n]
                n += 1

                if op <= OpCodes.OP_PUSHDATA4:
                    # Raw bytes follow
                    if op < OpCodes.OP_PUSHDATA1:
                        dlen = op
                    elif op == OpCodes.OP_PUSHDATA1:
                        dlen = script[n]
                        n += 1
                    elif op == OpCodes.OP_PUSHDATA2:
                        dlen, = unpack_le_uint16_from(script[n: n + 2])
                        n += 2
                    else:
                        dlen, = unpack_le_uint32_from(script[n: n + 4])
                        n += 4
                    if n + dlen > len(script):
                        raise IndexError
                    op = (op, script[n:n + dlen])
                    n += dlen

                ops.append(op)
        except Exception:
            # Truncated script; e.g. tx_hash
            # ebc9fa1196a59e192352d76c0f6e73167046b9d37b8302b6bb6968dfd279b767
            raise ScriptError('truncated script')

        return ops

    @classmethod
    def push_data(cls, data):
        """Returns the opcodes to push the data on the stack."""
        assert isinstance(data, (bytes, bytearray))

        n = len(data)
        if n < OpCodes.OP_PUSHDATA1:
            return bytes([n]) + data
        if n < 256:
            return bytes([OpCodes.OP_PUSHDATA1, n]) + data
        if n < 65536:
            return bytes([OpCodes.OP_PUSHDATA2]) + pack_le_uint16(n) + data
        return bytes([OpCodes.OP_PUSHDATA4]) + pack_le_uint32(n) + data

    @classmethod
    def opcode_name(cls, opcode):
        if OpCodes.OP_0 < opcode < OpCodes.OP_PUSHDATA1:
            return f'OP_{opcode:d}'
        try:
            return OpCodes.whatis(opcode)
        except KeyError:
            return f'OP_UNKNOWN:{opcode:d}'

    @classmethod
    def dump(cls, script):
        opcodes, datas = cls.get_ops(script)
        for opcode, data in zip(opcodes, datas):
            name = cls.opcode_name(opcode)
            if data is None:
                print(name)
            else:
                print(f'{name} {data.hex()} ({len(data):d} bytes)')
