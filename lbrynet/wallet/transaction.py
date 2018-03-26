import sys
import hashlib
import logging
import ecdsa
from ecdsa.curves import SECP256k1

from lbryschema.address import hash_160_bytes_to_address, public_key_to_address
from lbryschema.address import address_to_hash_160

from .constants import TYPE_SCRIPT, TYPE_PUBKEY, TYPE_UPDATE, TYPE_SUPPORT, TYPE_CLAIM
from .constants import TYPE_ADDRESS, NO_SIGNATURE
from .opcodes import opcodes, match_decoded, script_GetOp
from .bcd_data_stream import BCDataStream
from .hashing import Hash, hash_160, hash_encode
from .lbrycrd import op_push
from .lbrycrd import point_to_ser, MyVerifyingKey, MySigningKey
from .lbrycrd import regenerate_key, public_key_from_private_key
from .lbrycrd import encode_claim_id_hex, claim_id_hash
from .util import profiler, var_int, int_to_hex, parse_sig, rev_hex

log = logging.getLogger()


def parse_xpub(x_pubkey):
    if x_pubkey[0:2] in ['02', '03', '04']:
        pubkey = x_pubkey
    elif x_pubkey[0:2] == 'ff':
        from lbryum.bip32 import BIP32_Account
        xpub, s = BIP32_Account.parse_xpubkey(x_pubkey)
        pubkey = BIP32_Account.derive_pubkey_from_xpub(xpub, s[0], s[1])
    elif x_pubkey[0:2] == 'fd':
        addrtype = ord(x_pubkey[2:4].decode('hex'))
        hash160 = x_pubkey[4:].decode('hex')
        pubkey = None
        address = hash_160_bytes_to_address(hash160, addrtype)
    else:
        raise BaseException("Cannnot parse pubkey")
    if pubkey:
        address = public_key_to_address(pubkey.decode('hex'))
    return pubkey, address


def parse_scriptSig(d, bytes):
    try:
        decoded = [x for x in script_GetOp(bytes)]
    except Exception:
        # coinbase transactions raise an exception
        log.error("cannot find address in input script: {}".format(bytes.encode('hex')))
        return

    # payto_pubkey
    match = [opcodes.OP_PUSHDATA4]
    if match_decoded(decoded, match):
        sig = decoded[0][1].encode('hex')
        d['address'] = "(pubkey)"
        d['signatures'] = [sig]
        d['num_sig'] = 1
        d['x_pubkeys'] = ["(pubkey)"]
        d['pubkeys'] = ["(pubkey)"]
        return

    # non-generated TxIn transactions push a signature
    # (seventy-something bytes) and then their public key
    # (65 bytes) onto the stack:
    match = [opcodes.OP_PUSHDATA4, opcodes.OP_PUSHDATA4]
    if match_decoded(decoded, match):
        sig = decoded[0][1].encode('hex')
        x_pubkey = decoded[1][1].encode('hex')
        try:
            signatures = parse_sig([sig])
            pubkey, address = parse_xpub(x_pubkey)
        except:
            import traceback
            traceback.print_exc(file=sys.stdout)
            log.error("cannot find address in input script: {}".format(bytes.encode('hex')))
            return
        d['signatures'] = signatures
        d['x_pubkeys'] = [x_pubkey]
        d['num_sig'] = 1
        d['pubkeys'] = [pubkey]
        d['address'] = address
        return

    # p2sh transaction, m of n
    match = [opcodes.OP_0] + [opcodes.OP_PUSHDATA4] * (len(decoded) - 1)
    if not match_decoded(decoded, match):
        log.error("cannot find address in input script: {}".format(bytes.encode('hex')))
        return
    x_sig = [x[1].encode('hex') for x in decoded[1:-1]]
    dec2 = [x for x in script_GetOp(decoded[-1][1])]
    m = dec2[0][0] - opcodes.OP_1 + 1
    n = dec2[-2][0] - opcodes.OP_1 + 1
    op_m = opcodes.OP_1 + m - 1
    op_n = opcodes.OP_1 + n - 1
    match_multisig = [op_m] + [opcodes.OP_PUSHDATA4] * n + [op_n, opcodes.OP_CHECKMULTISIG]
    if not match_decoded(dec2, match_multisig):
        log.error("cannot find address in input script: {}".format(bytes.encode('hex')))
        return
    x_pubkeys = map(lambda x: x[1].encode('hex'), dec2[1:-2])
    pubkeys = [parse_xpub(x)[0] for x in x_pubkeys]  # xpub, addr = parse_xpub()
    redeemScript = Transaction.multisig_script(pubkeys, m)
    # write result in d
    d['num_sig'] = m
    d['signatures'] = parse_sig(x_sig)
    d['x_pubkeys'] = x_pubkeys
    d['pubkeys'] = pubkeys
    d['redeemScript'] = redeemScript
    d['address'] = hash_160_bytes_to_address(hash_160(redeemScript.decode('hex')), 5)


class NameClaim(object):
    def __init__(self, name, value):
        self.name = name
        self.value = value


class ClaimUpdate(object):
    def __init__(self, name, claim_id, value):
        self.name = name
        self.claim_id = claim_id
        self.value = value


class ClaimSupport(object):
    def __init__(self, name, claim_id):
        self.name = name
        self.claim_id = claim_id


def decode_claim_script(decoded_script):
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
    if not 0 <= decoded_script[op][0] <= opcodes.OP_PUSHDATA4:
        return False
    name = decoded_script[op][1]
    op += 1
    if not 0 <= decoded_script[op][0] <= opcodes.OP_PUSHDATA4:
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
    elif decoded_script[op][0] != opcodes.OP_2DROP and decoded_script[0][0] == \
            opcodes.OP_UPDATE_CLAIM:
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


def get_address_from_output_script(script_bytes):
    output_type = 0
    decoded = [x for x in script_GetOp(script_bytes)]
    r = decode_claim_script(decoded)
    claim_args = None
    if r is not False:
        claim_info, decoded = r
        if isinstance(claim_info, NameClaim):
            claim_args = (claim_info.name, claim_info.value)
            output_type |= TYPE_CLAIM
        elif isinstance(claim_info, ClaimSupport):
            claim_args = (claim_info.name, claim_info.claim_id)
            output_type |= TYPE_SUPPORT
        elif isinstance(claim_info, ClaimUpdate):
            claim_args = (claim_info.name, claim_info.claim_id, claim_info.value)
            output_type |= TYPE_UPDATE

    # The Genesis Block, self-payments, and pay-by-IP-address payments look like:
    # 65 BYTES:... CHECKSIG
    match_pubkey = [opcodes.OP_PUSHDATA4, opcodes.OP_CHECKSIG]

    # Pay-by-Bitcoin-address TxOuts look like:
    # DUP HASH160 20 BYTES:... EQUALVERIFY CHECKSIG
    match_p2pkh = [opcodes.OP_DUP, opcodes.OP_HASH160, opcodes.OP_PUSHDATA4, opcodes.OP_EQUALVERIFY,
                   opcodes.OP_CHECKSIG]

    # p2sh
    match_p2sh = [opcodes.OP_HASH160, opcodes.OP_PUSHDATA4, opcodes.OP_EQUAL]

    if match_decoded(decoded, match_pubkey):
        output_val = decoded[0][1].encode('hex')
        output_type |= TYPE_PUBKEY
    elif match_decoded(decoded, match_p2pkh):
        output_val = hash_160_bytes_to_address(decoded[2][1])
        output_type |= TYPE_ADDRESS
    elif match_decoded(decoded, match_p2sh):
        output_val = hash_160_bytes_to_address(decoded[1][1], 5)
        output_type |= TYPE_ADDRESS
    else:
        output_val = bytes
        output_type |= TYPE_SCRIPT

    if output_type & (TYPE_CLAIM | TYPE_SUPPORT | TYPE_UPDATE):
        output_val = (claim_args, output_val)

    return output_type, output_val


def parse_input(vds):
    d = {}
    prevout_hash = hash_encode(vds.read_bytes(32))
    prevout_n = vds.read_uint32()
    scriptSig = vds.read_bytes(vds.read_compact_size())
    d['scriptSig'] = scriptSig.encode('hex')
    sequence = vds.read_uint32()
    if prevout_hash == '00' * 32:
        d['is_coinbase'] = True
    else:
        d['is_coinbase'] = False
        d['prevout_hash'] = prevout_hash
        d['prevout_n'] = prevout_n
        d['sequence'] = sequence
        d['pubkeys'] = []
        d['signatures'] = {}
        d['address'] = None
        if scriptSig:
            parse_scriptSig(d, scriptSig)
    return d


def parse_output(vds, i):
    d = {}
    d['value'] = vds.read_int64()
    scriptPubKey = vds.read_bytes(vds.read_compact_size())
    d['type'], d['address'] = get_address_from_output_script(scriptPubKey)
    d['scriptPubKey'] = scriptPubKey.encode('hex')
    d['prevout_n'] = i
    return d


def deserialize(raw):
    vds = BCDataStream()
    vds.write(raw.decode('hex'))
    d = {}
    start = vds.read_cursor
    d['version'] = vds.read_int32()
    n_vin = vds.read_compact_size()
    d['inputs'] = list(parse_input(vds) for i in xrange(n_vin))
    n_vout = vds.read_compact_size()
    d['outputs'] = list(parse_output(vds, i) for i in xrange(n_vout))
    d['lockTime'] = vds.read_uint32()
    return d


def push_script(x):
    return op_push(len(x) / 2) + x


class Transaction(object):
    def __str__(self):
        if self.raw is None:
            self.raw = self.serialize()
        return self.raw

    def __init__(self, raw):
        if raw is None:
            self.raw = None
        elif type(raw) in [str, unicode]:
            self.raw = raw.strip() if raw else None
        elif type(raw) is dict:
            self.raw = raw['hex']
        else:
            raise BaseException("cannot initialize transaction", raw)
        self._inputs = None
        self._outputs = None

    def update(self, raw):
        self.raw = raw
        self._inputs = None
        self.deserialize()

    def inputs(self):
        if self._inputs is None:
            self.deserialize()
        return self._inputs

    def outputs(self):
        if self._outputs is None:
            self.deserialize()
        return self._outputs

    def update_signatures(self, raw):
        """Add new signatures to a transaction"""
        d = deserialize(raw)
        for i, txin in enumerate(self.inputs()):
            sigs1 = txin.get('signatures')
            sigs2 = d['inputs'][i].get('signatures')
            for sig in sigs2:
                if sig in sigs1:
                    continue
                for_sig = Hash(self.tx_for_sig(i).decode('hex'))
                # der to string
                order = ecdsa.ecdsa.generator_secp256k1.order()
                r, s = ecdsa.util.sigdecode_der(sig.decode('hex'), order)
                sig_string = ecdsa.util.sigencode_string(r, s, order)
                pubkeys = txin.get('pubkeys')
                compressed = True
                for recid in range(4):
                    public_key = MyVerifyingKey.from_signature(sig_string, recid, for_sig,
                                                               curve=SECP256k1)
                    pubkey = point_to_ser(public_key.pubkey.point, compressed).encode('hex')
                    if pubkey in pubkeys:
                        public_key.verify_digest(sig_string, for_sig,
                                                 sigdecode=ecdsa.util.sigdecode_string)
                        j = pubkeys.index(pubkey)
                        log.error("adding sig {} {} {} {}".format(i, j, pubkey, sig))
                        self._inputs[i]['signatures'][j] = sig
                        self._inputs[i]['x_pubkeys'][j] = pubkey
                        break
        # redo raw
        self.raw = self.serialize()

    def deserialize(self):
        if self.raw is None:
            self.raw = self.serialize()
        if self._inputs is not None:
            return
        d = deserialize(self.raw)
        self._inputs = d['inputs']
        self._outputs = [(x['type'], x['address'], x['value']) for x in d['outputs']]
        self.locktime = d['lockTime']
        return d

    @classmethod
    def from_io(cls, inputs, outputs, locktime=0):
        self = cls(None)
        self._inputs = inputs
        self._outputs = outputs
        self.locktime = locktime
        return self

    @classmethod
    def multisig_script(cls, public_keys, m):
        n = len(public_keys)
        assert n <= 15
        assert m <= n
        op_m = format(opcodes.OP_1 + m - 1, 'x')
        op_n = format(opcodes.OP_1 + n - 1, 'x')
        keylist = [op_push(len(k) / 2) + k for k in public_keys]
        return op_m + ''.join(keylist) + op_n + 'ae'

    @classmethod
    def pay_script(cls, output_type, addr):
        script = ''
        if output_type & TYPE_CLAIM:
            claim, addr = addr
            claim_name, claim_value = claim
            script += 'b5'  # op_claim_name
            script += push_script(claim_name.encode('hex'))
            script += push_script(claim_value.encode('hex'))
            script += '6d75'  # op_2drop, op_drop
        elif output_type & TYPE_SUPPORT:
            claim, addr = addr
            claim_name, claim_id = claim
            script += 'b6'
            script += push_script(claim_name.encode('hex'))
            script += push_script(claim_id.encode('hex'))
            script += '6d75'
        elif output_type & TYPE_UPDATE:
            claim, addr = addr
            claim_name, claim_id, claim_value = claim
            script += 'b7'
            script += push_script(claim_name.encode('hex'))
            script += push_script(claim_id.encode('hex'))
            script += push_script(claim_value.encode('hex'))
            script += '6d6d'

        if output_type & TYPE_SCRIPT:
            script += addr.encode('hex')
        elif output_type & TYPE_ADDRESS:  # op_2drop, op_drop
            addrtype, hash_160 = address_to_hash_160(addr)
            if addrtype == 0:
                script += '76a9'  # op_dup, op_hash_160
                script += push_script(hash_160.encode('hex'))
                script += '88ac'  # op_equalverify, op_checksig
            elif addrtype == 5:
                script += 'a9'  # op_hash_160
                script += push_script(hash_160.encode('hex'))
                script += '87'  # op_equal
            else:
                raise Exception("Unknown address type: %s" % addrtype)
        else:
            raise Exception("Unknown output type: %s" % output_type)
        return script

    @classmethod
    def input_script(cls, txin, i, for_sig):
        # for_sig:
        #   -1   : do not sign, estimate length
        #   i>=0 : serialized tx for signing input i
        #   None : add all known signatures

        p2sh = txin.get('redeemScript') is not None
        num_sig = txin['num_sig'] if p2sh else 1
        address = txin['address']

        x_signatures = txin['signatures']
        signatures = filter(None, x_signatures)
        is_complete = len(signatures) == num_sig

        if for_sig in [-1, None]:
            # if we have enough signatures, we use the actual pubkeys
            # use extended pubkeys (with bip32 derivation)
            if for_sig == -1:
                # we assume that signature will be 0x48 bytes long
                pubkeys = txin['pubkeys']
                sig_list = ["00" * 0x48] * num_sig
            elif is_complete:
                pubkeys = txin['pubkeys']
                sig_list = ((sig + '01') for sig in signatures)
            else:
                pubkeys = txin['x_pubkeys']
                sig_list = ((sig + '01') if sig else NO_SIGNATURE for sig in x_signatures)
            script = ''.join(push_script(x) for x in sig_list)
            if not p2sh:
                x_pubkey = pubkeys[0]
                if x_pubkey is None:
                    addrtype, h160 = address_to_hash_160(txin['address'])
                    x_pubkey = 'fd' + (chr(addrtype) + h160).encode('hex')
                script += push_script(x_pubkey)
            else:
                script = '00' + script  # put op_0 in front of script
                redeem_script = cls.multisig_script(pubkeys, num_sig)
                script += push_script(redeem_script)

        elif for_sig == i:
            script_type = TYPE_ADDRESS
            if 'is_claim' in txin and txin['is_claim']:
                script_type |= TYPE_CLAIM
                address = ((txin['claim_name'], txin['claim_value']), address)
            elif 'is_support' in txin and txin['is_support']:
                script_type |= TYPE_SUPPORT
                address = ((txin['claim_name'], txin['claim_id']), address)
            elif 'is_update' in txin and txin['is_update']:
                script_type |= TYPE_UPDATE
                address = ((txin['claim_name'], txin['claim_id'], txin['claim_value']), address)
            script = txin['redeemScript'] if p2sh else cls.pay_script(script_type, address)
        else:
            script = ''

        return script

    @classmethod
    def serialize_input(cls, txin, i, for_sig):
        # Prev hash and index
        s = txin['prevout_hash'].decode('hex')[::-1].encode('hex')
        s += int_to_hex(txin['prevout_n'], 4)
        # Script length, script, sequence
        script = cls.input_script(txin, i, for_sig)
        s += var_int(len(script) / 2)
        s += script
        s += "ffffffff"
        return s

    def BIP_LI01_sort(self):
        # See https://github.com/kristovatlas/rfc/blob/master/bips/bip-li01.mediawiki
        self._inputs.sort(key=lambda i: (i['prevout_hash'], i['prevout_n']))
        self._outputs.sort(key=lambda o: (o[2], self.pay_script(o[0], o[1])))

    def serialize(self, for_sig=None):
        inputs = self.inputs()
        outputs = self.outputs()
        s = int_to_hex(1, 4)  # version
        s += var_int(len(inputs))  # number of inputs
        for i, txin in enumerate(inputs):
            s += self.serialize_input(txin, i, for_sig)
        s += var_int(len(outputs))  # number of outputs
        for output in outputs:
            output_type, addr, amount = output
            s += int_to_hex(amount, 8)  # amount
            script = self.pay_script(output_type, addr)
            s += var_int(len(script) / 2)  # script length
            s += script  # script
        s += int_to_hex(0, 4)  # lock time
        if for_sig is not None and for_sig != -1:
            s += int_to_hex(1, 4)  # hash type
        return s

    def tx_for_sig(self, i):
        return self.serialize(for_sig=i)

    def hash(self):
        return Hash(self.raw.decode('hex'))[::-1].encode('hex')

    def get_claim_id(self, nout):
        if nout < 0:
            raise IndexError
        if not self._outputs[nout][0] & TYPE_CLAIM:
            raise ValueError
        tx_hash = rev_hex(self.hash()).decode('hex')
        return encode_claim_id_hex(claim_id_hash(tx_hash, nout))

    def add_inputs(self, inputs):
        self._inputs.extend(inputs)
        self.raw = None

    def add_outputs(self, outputs):
        self._outputs.extend(outputs)
        self.raw = None

    def input_value(self):
        return sum(x['value'] for x in self.inputs())

    def output_value(self):
        return sum(val for tp, addr, val in self.outputs())

    def get_fee(self):
        return self.input_value() - self.output_value()

    def is_final(self):
        return not any([x.get('sequence') < 0xffffffff - 1 for x in self.inputs()])

    @classmethod
    def fee_for_size(cls, relay_fee, fee_per_kb, size):
        '''Given a fee per kB in satoshis, and a tx size in bytes,
        returns the transaction fee.'''
        fee = int(fee_per_kb * size / 1000.)
        if fee < relay_fee:
            fee = relay_fee
        return fee

    @profiler
    def estimated_size(self):
        '''Return an estimated tx size in bytes.'''
        return len(self.serialize(-1)) / 2  # ASCII hex string

    @classmethod
    def estimated_input_size(cls, txin):
        '''Return an estimated of serialized input size in bytes.'''
        return len(cls.serialize_input(txin, -1, -1)) / 2

    def estimated_fee(self, relay_fee, fee_per_kb):
        '''Return an estimated fee given a fee per kB in satoshis.'''
        return self.fee_for_size(relay_fee, fee_per_kb, self.estimated_size())

    def signature_count(self):
        r = 0
        s = 0
        for txin in self.inputs():
            if txin.get('is_coinbase'):
                continue
            signatures = filter(None, txin.get('signatures', []))
            s += len(signatures)
            r += txin.get('num_sig', -1)
        return s, r

    def is_complete(self):
        s, r = self.signature_count()
        return r == s

    def inputs_without_script(self):
        out = set()
        for i, txin in enumerate(self.inputs()):
            if txin.get('scriptSig') == '':
                out.add(i)
        return out

    def inputs_to_sign(self):
        out = set()
        for txin in self.inputs():
            num_sig = txin.get('num_sig')
            if num_sig is None:
                continue
            x_signatures = txin['signatures']
            signatures = filter(None, x_signatures)
            if len(signatures) == num_sig:
                # input is complete
                continue
            for k, x_pubkey in enumerate(txin['x_pubkeys']):
                if x_signatures[k] is not None:
                    # this pubkey already signed
                    continue
                out.add(x_pubkey)
        return out

    def sign(self, keypairs):
        for i, txin in enumerate(self.inputs()):
            num = txin['num_sig']
            for x_pubkey in txin['x_pubkeys']:
                signatures = filter(None, txin['signatures'])
                if len(signatures) == num:
                    # txin is complete
                    break
                if x_pubkey in keypairs.keys():
                    log.debug("adding signature for %s", x_pubkey)
                    # add pubkey to txin
                    txin = self._inputs[i]
                    x_pubkeys = txin['x_pubkeys']
                    ii = x_pubkeys.index(x_pubkey)
                    sec = keypairs[x_pubkey]
                    pubkey = public_key_from_private_key(sec)
                    txin['x_pubkeys'][ii] = pubkey
                    txin['pubkeys'][ii] = pubkey
                    self._inputs[i] = txin
                    # add signature
                    for_sig = Hash(self.tx_for_sig(i).decode('hex'))
                    pkey = regenerate_key(sec)
                    secexp = pkey.secret
                    private_key = MySigningKey.from_secret_exponent(secexp, curve=SECP256k1)
                    public_key = private_key.get_verifying_key()
                    sig = private_key.sign_digest_deterministic(for_sig, hashfunc=hashlib.sha256,
                                                                sigencode=ecdsa.util.sigencode_der)
                    assert public_key.verify_digest(sig, for_sig,
                                                    sigdecode=ecdsa.util.sigdecode_der)
                    txin['signatures'][ii] = sig.encode('hex')
                    self._inputs[i] = txin
        log.debug("is_complete: %s", self.is_complete())
        self.raw = self.serialize()

    def get_outputs(self):
        """convert pubkeys to addresses"""
        o = []
        for type, x, v in self.outputs():
            if type & (TYPE_CLAIM | TYPE_UPDATE | TYPE_SUPPORT):
                x = x[1]
            if type & TYPE_ADDRESS:
                addr = x
            elif type & TYPE_PUBKEY:
                addr = public_key_to_address(x.decode('hex'))
            else:
                addr = 'SCRIPT ' + x.encode('hex')
            o.append((addr, v))  # consider using yield (addr, v)
        return o

    def get_output_addresses(self):
        return [addr for addr, val in self.get_outputs()]

    def has_address(self, addr):
        return (addr in self.get_output_addresses()) or (
            addr in (tx.get("address") for tx in self.inputs()))

    def as_dict(self):
        if self.raw is None:
            self.raw = self.serialize()
        self.deserialize()
        out = {
            'hex': self.raw,
            'complete': self.is_complete()
        }
        return out

    def requires_fee(self, wallet):
        # see https://en.bitcoin.it/wiki/Transaction_fees
        #
        # size must be smaller than 1 kbyte for free tx
        size = len(self.serialize(-1)) / 2
        if size >= 10000:
            return True
        # all outputs must be 0.01 BTC or larger for free tx
        for addr, value in self.get_outputs():
            if value < 1000000:
                return True
        # priority must be large enough for free tx
        threshold = 57600000
        weight = 0
        for txin in self.inputs():
            age = wallet.get_confirmations(txin["prevout_hash"])[0]
            weight += txin["value"] * age
        priority = weight / size
        log.error("{} {}".format(priority, threshold))

        return priority < threshold
