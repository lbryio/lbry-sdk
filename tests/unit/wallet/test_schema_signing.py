from binascii import unhexlify

from lbry.testcase import AsyncioTestCase
from lbry.wallet.constants import CENT, NULL_HASH32
from lbry.wallet.bip32 import PrivateKey, KeyPath
from lbry.wallet.mnemonic import Mnemonic
from lbry.wallet import Ledger, Database, Headers, Transaction, Input, Output
from lbry.schema.claim import Claim
from lbry.crypto.hash import sha256


def get_output(amount=CENT, pubkey_hash=NULL_HASH32):
    return Transaction() \
        .add_outputs([Output.pay_pubkey_hash(amount, pubkey_hash)]) \
        .outputs[0]


def get_input():
    return Input.spend(get_output())


def get_tx():
    return Transaction().add_inputs([get_input()])


async def get_channel(claim_name='@foo'):
    seed = Mnemonic.mnemonic_to_seed(Mnemonic().make_seed(), '')
    key = PrivateKey.from_seed(Ledger, seed)
    channel_key = key.child(KeyPath.CHANNEL).child(0)
    channel_txo = Output.pay_claim_name_pubkey_hash(CENT, claim_name, Claim(), b'abc')
    channel_txo.set_channel_private_key(channel_key)
    get_tx().add_outputs([channel_txo])
    return channel_txo


def get_stream(claim_name='foo'):
    stream_txo = Output.pay_claim_name_pubkey_hash(CENT, claim_name, Claim(), b'abc')
    get_tx().add_outputs([stream_txo])
    return stream_txo


class TestSigningAndValidatingClaim(AsyncioTestCase):

    async def test_successful_create_sign_and_validate(self):
        channel = await get_channel()
        stream = get_stream()
        stream.sign(channel)
        self.assertTrue(stream.is_signed_by(channel))

    async def test_fail_to_validate_on_wrong_channel(self):
        stream = get_stream()
        stream.sign(await get_channel())
        self.assertFalse(stream.is_signed_by(await get_channel()))

    async def test_fail_to_validate_altered_claim(self):
        channel = await get_channel()
        stream = get_stream()
        stream.sign(channel)
        self.assertTrue(stream.is_signed_by(channel))
        stream.claim.stream.title = 'hello'
        self.assertFalse(stream.is_signed_by(channel))

    async def test_valid_private_key_for_cert(self):
        channel = await get_channel()
        self.assertTrue(channel.is_channel_private_key(channel.private_key))

    async def test_fail_to_load_wrong_private_key_for_cert(self):
        channel = await get_channel()
        self.assertFalse(channel.is_channel_private_key((await get_channel()).private_key))


class TestValidatingOldSignatures(AsyncioTestCase):

    def test_signed_claim_made_by_ytsync(self):
        stream_tx = Transaction(unhexlify(
            b'0100000001eb2a756e15bde95db3d2ae4a6e9b2796a699087890644607b5b04a5f15b67062010000006a4'
            b'7304402206444b920bd318a07d9b982e30eb66245fdaaa6c9866e1f6e5900161d9b0ffd70022036464714'
            b'4f1830898a2042aa0d6cef95a243799cc6e36630a58d411e2f9111f00121029b15f9a00a7c3f21b10bd4b'
            b'98ab23a9e895bd9160e21f71317862bf55fbbc89effffffff0240420f0000000000fd1503b52268657265'
            b'2d6172652d352d726561736f6e732d692d6e657874636c6f75642d746c674dd302080110011aee0408011'
            b'2a604080410011a2b4865726520617265203520526561736f6e73204920e29da4efb88f204e657874636c'
            b'6f7564207c20544c4722920346696e64206f7574206d6f72652061626f7574204e657874636c6f75643a2'
            b'068747470733a2f2f6e657874636c6f75642e636f6d2f0a0a596f752063616e2066696e64206d65206f6e'
            b'20746865736520736f6369616c733a0a202a20466f72756d733a2068747470733a2f2f666f72756d2e686'
            b'5617679656c656d656e742e696f2f0a202a20506f64636173743a2068747470733a2f2f6f6666746f7069'
            b'63616c2e6e65740a202a2050617472656f6e3a2068747470733a2f2f70617472656f6e2e636f6d2f74686'
            b'56c696e757867616d65720a202a204d657263683a2068747470733a2f2f746565737072696e672e636f6d'
            b'2f73746f7265732f6f6666696369616c2d6c696e75782d67616d65720a202a205477697463683a2068747'
            b'470733a2f2f7477697463682e74762f786f6e64616b0a202a20547769747465723a2068747470733a2f2f'
            b'747769747465722e636f6d2f7468656c696e757867616d65720a0a2e2e2e0a68747470733a2f2f7777772'
            b'e796f75747562652e636f6d2f77617463683f763d4672546442434f535f66632a0f546865204c696e7578'
            b'2047616d6572321c436f7079726967687465642028636f6e7461637420617574686f722938004a2968747'
            b'470733a2f2f6265726b2e6e696e6a612f7468756d626e61696c732f4672546442434f535f666352005a00'
            b'1a41080110011a30040e8ac6e89c061f982528c23ad33829fd7146435bf7a4cc22f0bff70c4fe0b91fd36'
            b'da9a375e3e1c171db825bf5d1f32209766964656f2f6d70342a5c080110031a4062b2dd4c45e364030fbf'
            b'ad1a6fefff695ebf20ea33a5381b947753e2a0ca359989a5cc7d15e5392a0d354c0b68498382b2701b22c'
            b'03beb8dcb91089031b871e72214feb61536c007cdf4faeeaab4876cb397feaf6b516d7576a914f4f43f6f'
            b'7a472bbf27fa3630329f771135fc445788ac86ff0600000000001976a914cef0fe3eeaf04416f0c3ff3e7'
            b'8a598a081e70ee788ac00000000'
        ))
        stream = stream_tx.outputs[0]

        channel_tx = Transaction(unhexlify(
            b'010000000192a1e1e3f66b8ca05a021cfa5fb6645ebc066b46639ccc9b3781fa588a88da65010000006a4'
            b'7304402206be09a355f6abea8a10b5512180cd258460b42d516b5149431ffa3230a02533a0220325e83c6'
            b'176b295d633b18aad67adb4ad766d13152536ac04583f86d14645c9901210269c63bc8bac8143ef02f972'
            b'4a4ab35b12bdfa65ee1ad8c0db3d6511407a4cc2effffffff0240420f000000000091b50e405468654c69'
            b'6e757847616d65724c6408011002225e0801100322583056301006072a8648ce3d020106052b8104000a0'
            b'34200043878b1edd4a1373149909ef03f4339f6da9c2bd2214c040fd2e530463ffe66098eca14fc70b50f'
            b'f3aefd106049a815f595ed5a13eda7419ad78d9ed7ae473f176d7576a914994dad5f21c384ff526749b87'
            b'6d9d017d257b69888ac00dd6d00000000001976a914979202508a44f0e8290cea80787c76f98728845388'
            b'ac00000000'
        ))
        channel = channel_tx.outputs[0]

        ledger = Ledger({
            'db': Database(':memory:'),
            'headers': Headers(':memory:')
        })

        self.assertTrue(stream.is_signed_by(channel, ledger))

    def test_claim_signed_using_ecdsa_validates_with_coincurve(self):
        channel_tx = Transaction(unhexlify(
            "0100000001b91d829283c0d80cb8113d5f36b6da3dfe9df3e783f158bfb3fd1b2b178d7fc9010000006b48"
            "3045022100f4e2b4ee38388c3d3a62f4b12fdd413f6f140168e85884bbeb33a3f2d3159ef502201721200f"
            "4a4f3b87484d4f47c9054e31cd3ba451dd3886a7f9f854893e7c8cf90121023f9e906e0c120f3bf74feb40"
            "f01ddeafbeb1856d91938c3bef25bed06767247cffffffff0200e1f5050000000081b505406368616e4c5d"
            "00125a0a583056301006072a8648ce3d020106052b8104000a03420004d7fa13fd8e57f3a0b878eaaf3d17"
            "9144d25ddbe4a3e4440a661f51b4134c6a13c9c98678ff8411932e60fd97d7baf03ea67ebcc21097230cfb"
            "2241348aadb55e6d7576a9149c6d700f89c77f0e8c650ba05656f8f2392782d388acf47c95350000000019"
            "76a914d9502233e0e1fc76e13e36c546f704c3124d5eaa88ac00000000"
        ))
        channel = channel_tx.outputs[0]

        stream_tx = Transaction(unhexlify(
            "010000000116a1d90763f2e3a2348c7fb438a23f232b15e3ffe3f058c3b2ab52c8bed8dcb5010000006b48"
            "30450221008f38561b3a16944c63b4f4f1562f1efe1b2060f31d249e234003ee5e3461756f02205773c99e"
            "83c968728e4f2433a13871c6ad23f6c10368ac52fa62a09f3f7ef5fd012102597f39845b98e2415b777aa0"
            "3849d346d287af7970deb05f11214b3418ae9d82ffffffff0200e1f50500000000fd0c01b505636c61696d"
            "4ce8012e6e40fa5fee1b915af3b55131dcbcebee34ab9148292b084ce3741f2e0db49783f3d854ac885f2b"
            "6304a76ef7048046e338dd414ba4c64e8468651768ffaaf550c8560637ac8c477ea481ac2a9264097240f4"
            "ab0a90010a8d010a3056bf5dbae43f77a63d075b0f2ae9c7c3e3098db93779c7f9840da0f4db9c2f8c8454"
            "f4edd1373e2b64ee2e68350d916e120b746d706c69647879363171180322186170706c69636174696f6e2f"
            "6f637465742d73747265616d3230f293f5acf4310562d4a41f6620167fe6d83761a98d36738908ce5c8776"
            "1642710e55352a396276a42eda92ff5856f46f6d7576a91434bd3dc4c45cc0635eb2ad5da658727e5442ca"
            "0f88ace82f902f000000001976a91427b27c89eaebf68d063c107241584c07e5a6ccc688ac00000000"
        ))
        stream = stream_tx.outputs[0]

        ledger = Ledger({'db': Database(':memory:'), 'headers': Headers(':memory:')})
        self.assertTrue(stream.is_signed_by(channel, ledger))


class TestValidateSignContent(AsyncioTestCase):

    async def test_sign_some_content(self):
        some_content = "MEANINGLESS CONTENT AEE3353320".encode()
        timestamp_str = "1630564175"
        channel = await get_channel()
        signature = channel.sign_data(some_content, timestamp_str)
        pieces = [timestamp_str.encode(), channel.claim_hash, some_content]
        self.assertTrue(Output.is_signature_valid(
            unhexlify(signature.encode()),
            sha256(b''.join(pieces)),
            channel.claim.channel.public_key_bytes
        ))
