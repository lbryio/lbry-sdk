from unittest import TestCase
from binascii import unhexlify

from lbry.schema import Claim


class TestOldJSONSchemaCompatibility(TestCase):

    def test_old_json_schema_v1(self):
        claim = Claim.from_bytes(
            b'{"fee": {"LBC": {"amount": 1.0, "address": "bPwGA9h7uijoy5uAvzVPQw9QyLoYZehHJo"}}, "d'
            b'escription": "10MB test file to measure download speed on Lbry p2p-network.", "licens'
            b'e": "None", "author": "root", "language": "English", "title": "10MB speed test file",'
            b' "sources": {"lbry_sd_hash": "bbd1f68374ff9a1044a90d7dd578ce41979211c386caf19e6f49653'
            b'6db5f2c96b58fe2c7a6677b331419a117873b539f"}, "content-type": "application/octet-strea'
            b'm", "thumbnail": "/home/robert/lbry/speed.jpg"}'
        )
        stream = claim.stream
        self.assertEqual(stream.title, '10MB speed test file')
        self.assertEqual(stream.description, '10MB test file to measure download speed on Lbry p2p-network.')
        self.assertEqual(stream.license, 'None')
        self.assertEqual(stream.author, 'root')
        self.assertEqual(stream.langtags, ['en'])
        self.assertEqual(stream.source.media_type, 'application/octet-stream')
        self.assertEqual(stream.thumbnail.url, '/home/robert/lbry/speed.jpg')
        self.assertEqual(
            stream.source.sd_hash,
            'bbd1f68374ff9a1044a90d7dd578ce41979211c386caf19e'
            '6f496536db5f2c96b58fe2c7a6677b331419a117873b539f'
        )
        self.assertEqual(stream.fee.address, 'bPwGA9h7uijoy5uAvzVPQw9QyLoYZehHJo')
        self.assertEqual(stream.fee.lbc, 1)
        self.assertEqual(stream.fee.dewies, 100000000)
        self.assertEqual(stream.fee.currency, 'LBC')
        with self.assertRaisesRegex(ValueError, 'USD can only be returned for USD fees.'):
            print(stream.fee.usd)

    def test_old_json_schema_v2(self):
        claim = Claim.from_bytes(
            b'{"license": "Creative Commons Attribution 3.0 United States", "fee": {"LBC": {"amount'
            b'": 10, "address": "bFro33qBKxnL1AsjUU9N4AQHp9V62Nhc5L"}}, "ver": "0.0.2", "descriptio'
            b'n": "Force P0 State for Nividia Cards! (max mining performance)", "language": "en", "'
            b'author": "Mii", "title": "Nividia P0", "sources": {"lbry_sd_hash": "c5ffee0fa5168e166'
            b'81b519d9d85446e8d1d818a616bd55540aa7374d2321b51abf2ac3dae1443a03dadcc8f7affaa62"}, "n'
            b'sfw": false, "license_url": "https://creativecommons.org/licenses/by/3.0/us/legalcode'
            b'", "content-type": "application/x-msdownload"}'
        )
        stream = claim.stream
        self.assertEqual(stream.title, 'Nividia P0')
        self.assertEqual(stream.description, 'Force P0 State for Nividia Cards! (max mining performance)')
        self.assertEqual(stream.license, 'Creative Commons Attribution 3.0 United States')
        self.assertEqual(stream.license_url, 'https://creativecommons.org/licenses/by/3.0/us/legalcode')
        self.assertEqual(stream.author, 'Mii')
        self.assertEqual(stream.langtags, ['en'])
        self.assertEqual(stream.source.media_type, 'application/x-msdownload')
        self.assertEqual(
            stream.source.sd_hash,
            'c5ffee0fa5168e16681b519d9d85446e8d1d818a616bd555'
            '40aa7374d2321b51abf2ac3dae1443a03dadcc8f7affaa62'
        )
        self.assertEqual(stream.fee.address, 'bFro33qBKxnL1AsjUU9N4AQHp9V62Nhc5L')
        self.assertEqual(stream.fee.lbc, 10)
        self.assertEqual(stream.fee.dewies, 1000000000)
        self.assertEqual(stream.fee.currency, 'LBC')
        with self.assertRaisesRegex(ValueError, 'USD can only be returned for USD fees.'):
            print(stream.fee.usd)

    def test_old_json_schema_v3(self):
        claim = Claim.from_bytes(
            b'{"ver": "0.0.3", "description": "asd", "license": "Creative Commons Attribution 4.0 I'
            b'nternational", "author": "sgb", "title": "ads", "language": "en", "sources": {"lbry_s'
            b'd_hash": "d83db664c6d7d570aa824300f4869e0bfb560e765efa477aebf566467f8d3a57f4f8c704cab'
            b'1308eb75ff8b7e84e3caf"}, "content_type": "video/mp4", "nsfw": false}'
        )
        stream = claim.stream
        self.assertEqual(stream.title, 'ads')
        self.assertEqual(stream.description, 'asd')
        self.assertEqual(stream.license, 'Creative Commons Attribution 4.0 International')
        self.assertEqual(stream.author, 'sgb')
        self.assertEqual(stream.langtags, ['en'])
        self.assertEqual(stream.source.media_type, 'video/mp4')
        self.assertEqual(
            stream.source.sd_hash,
            'd83db664c6d7d570aa824300f4869e0bfb560e765efa477a'
            'ebf566467f8d3a57f4f8c704cab1308eb75ff8b7e84e3caf'
        )


class TestTypesV1Compatibility(TestCase):

    def test_signed_claim_made_by_ytsync(self):
        claim = Claim.from_bytes(unhexlify(
            b'080110011aee04080112a604080410011a2b4865726520617265203520526561736f6e73204920e29da4e'
            b'fb88f204e657874636c6f7564207c20544c4722920346696e64206f7574206d6f72652061626f7574204e'
            b'657874636c6f75643a2068747470733a2f2f6e657874636c6f75642e636f6d2f0a0a596f752063616e206'
            b'6696e64206d65206f6e20746865736520736f6369616c733a0a202a20466f72756d733a2068747470733a'
            b'2f2f666f72756d2e6865617679656c656d656e742e696f2f0a202a20506f64636173743a2068747470733'
            b'a2f2f6f6666746f706963616c2e6e65740a202a2050617472656f6e3a2068747470733a2f2f7061747265'
            b'6f6e2e636f6d2f7468656c696e757867616d65720a202a204d657263683a2068747470733a2f2f7465657'
            b'37072696e672e636f6d2f73746f7265732f6f6666696369616c2d6c696e75782d67616d65720a202a2054'
            b'77697463683a2068747470733a2f2f7477697463682e74762f786f6e64616b0a202a20547769747465723'
            b'a2068747470733a2f2f747769747465722e636f6d2f7468656c696e757867616d65720a0a2e2e2e0a6874'
            b'7470733a2f2f7777772e796f75747562652e636f6d2f77617463683f763d4672546442434f535f66632a0'
            b'f546865204c696e75782047616d6572321c436f7079726967687465642028636f6e746163742061757468'
            b'6f722938004a2968747470733a2f2f6265726b2e6e696e6a612f7468756d626e61696c732f46725464424'
            b'34f535f666352005a001a41080110011a30040e8ac6e89c061f982528c23ad33829fd7146435bf7a4cc22'
            b'f0bff70c4fe0b91fd36da9a375e3e1c171db825bf5d1f32209766964656f2f6d70342a5c080110031a406'
            b'2b2dd4c45e364030fbfad1a6fefff695ebf20ea33a5381b947753e2a0ca359989a5cc7d15e5392a0d354c'
            b'0b68498382b2701b22c03beb8dcb91089031b871e72214feb61536c007cdf4faeeaab4876cb397feaf6b51'
        ))
        stream = claim.stream
        self.assertEqual(stream.title, 'Here are 5 Reasons I ❤️ Nextcloud | TLG')
        self.assertEqual(
            stream.description,
            'Find out more about Nextcloud: https://nextcloud.com/\n\nYou can find me on these soci'
            'als:\n * Forums: https://forum.heavyelement.io/\n * Podcast: https://offtopical.net\n '
            '* Patreon: https://patreon.com/thelinuxgamer\n * Merch: https://teespring.com/stores/o'
            'fficial-linux-gamer\n * Twitch: https://twitch.tv/xondak\n * Twitter: https://twitter.'
            'com/thelinuxgamer\n\n...\nhttps://www.youtube.com/watch?v=FrTdBCOS_fc'
        )
        self.assertEqual(stream.license, 'Copyrighted (contact author)')
        self.assertEqual(stream.author, 'The Linux Gamer')
        self.assertEqual(stream.langtags, ['en'])
        self.assertEqual(stream.source.media_type, 'video/mp4')
        self.assertEqual(stream.thumbnail.url, 'https://berk.ninja/thumbnails/FrTdBCOS_fc')
        self.assertEqual(
            stream.source.sd_hash,
            '040e8ac6e89c061f982528c23ad33829fd7146435bf7a4cc'
            '22f0bff70c4fe0b91fd36da9a375e3e1c171db825bf5d1f3'
        )

        # certificate for above channel
        cert = Claim.from_bytes(unhexlify(
            b'08011002225e0801100322583056301006072a8648ce3d020106052b8104000a034200043878b1edd4a13'
            b'73149909ef03f4339f6da9c2bd2214c040fd2e530463ffe66098eca14fc70b50ff3aefd106049a815f595'
            b'ed5a13eda7419ad78d9ed7ae473f17'
        ))
        channel = cert.channel
        self.assertEqual(
            channel.public_key,
            '3056301006072a8648ce3d020106052b8104000a034200043878b1edd4a1373149909ef03f4339f6da9c2b'
            'd2214c040fd2e530463ffe66098eca14fc70b50ff3aefd106049a815f595ed5a13eda7419ad78d9ed7ae47'
            '3f17'
        )

    def test_unsigned_with_fee(self):
        claim = Claim.from_bytes(unhexlify(
            b'080110011ad6010801127c080410011a08727067206d69646922046d6964692a08727067206d696469322'
            b'e437265617469766520436f6d6d6f6e73204174747269627574696f6e20342e3020496e7465726e617469'
            b'6f6e616c38004224080110011a19553f00bc139bbf40de425f94d51fffb34c1bea6d9171cd374c2500007'
            b'0414a0052005a001a54080110011a301f41eb0312aa7e8a5ce49349bc77d811da975833719d751523b19f'
            b'123fc3d528d6a94e3446ccddb7b9329f27a9cad7e3221c6170706c69636174696f6e2f782d7a69702d636'
            b'f6d70726573736564'
        ))
        stream = claim.stream
        self.assertEqual(stream.title, 'rpg midi')
        self.assertEqual(stream.description, 'midi')
        self.assertEqual(stream.license, 'Creative Commons Attribution 4.0 International')
        self.assertEqual(stream.author, 'rpg midi')
        self.assertEqual(stream.langtags, ['en'])
        self.assertEqual(stream.source.media_type, 'application/x-zip-compressed')
        self.assertEqual(
            stream.source.sd_hash,
            '1f41eb0312aa7e8a5ce49349bc77d811da975833719d7515'
            '23b19f123fc3d528d6a94e3446ccddb7b9329f27a9cad7e3'
        )
        self.assertEqual(stream.fee.address, 'bJUQ9MxS9N6M29zsA5GTpVSDzsnPjMBBX9')
        self.assertEqual(stream.fee.lbc, 15)
        self.assertEqual(stream.fee.dewies, 1500000000)
        self.assertEqual(stream.fee.currency, 'LBC')
        with self.assertRaisesRegex(ValueError, 'USD can only be returned for USD fees.'):
            print(stream.fee.usd)
