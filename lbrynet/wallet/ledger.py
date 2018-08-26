import logging

from six import int2byte
from binascii import unhexlify

from twisted.internet import defer

from .resolve import Resolver
from lbryschema.error import URIParseError
from lbryschema.uri import parse_lbry_uri
from torba.baseledger import BaseLedger

from .account import Account
from .network import Network
from .database import WalletDatabase
from .transaction import Transaction
from .header import Headers, UnvalidatedHeaders


log = logging.getLogger(__name__)


class MainNetLedger(BaseLedger):
    name = 'LBRY Credits'
    symbol = 'LBC'
    network_name = 'mainnet'

    account_class = Account
    database_class = WalletDatabase
    headers_class = Headers
    network_class = Network
    transaction_class = Transaction

    secret_prefix = int2byte(0x1c)
    pubkey_address_prefix = int2byte(0x55)
    script_address_prefix = int2byte(0x7a)
    extended_public_key_prefix = unhexlify('0488b21e')
    extended_private_key_prefix = unhexlify('0488ade4')

    max_target = 0x0000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '9c89283ba0f3227f6c03b70216b9f665f0118d5e0fa729cedf4fb34d6a34f463'
    genesis_bits = 0x1f00ffff
    target_timespan = 150

    default_fee_per_byte = 50
    default_fee_per_name_char = 200000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fee_per_name_char = self.config.get('fee_per_name_char', self.default_fee_per_name_char)

    @defer.inlineCallbacks
    def resolve(self, page, page_size, *uris):
        for uri in uris:
            try:
                parse_lbry_uri(uri)
            except URIParseError as err:
                defer.returnValue({'error': err.message})
        resolutions = yield self.network.get_values_for_uris(self.headers.hash().decode(), *uris)
        resolver = Resolver(self.headers.claim_trie_root, self.headers.height, self.transaction_class,
                            hash160_to_address=lambda x: self.hash160_to_address(x), network=self.network)
        defer.returnValue((yield resolver._handle_resolutions(resolutions, uris, page, page_size)))

    def get_claim_by_claim_id(self, claim_id):
        d = self.network.get_claims_by_ids(claim_id)
        d.addCallback(lambda result: result.pop(claim_id) if result else {})
        resolver = Resolver(self.headers.claim_trie_root, self.headers.height, self.transaction_class,
                            hash160_to_address=lambda x: self.hash160_to_address(x), network=self.network)
        d.addCallback(resolver.get_cert_and_validate_result)
        return d

    @defer.inlineCallbacks
    def start(self):
        yield super().start()
        yield defer.DeferredList([
            a.maybe_migrate_certificates() for a in self.accounts
        ])


class TestNetLedger(MainNetLedger):
    network_name = 'testnet'
    pubkey_address_prefix = int2byte(111)
    script_address_prefix = int2byte(196)
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')


class RegTestLedger(MainNetLedger):
    network_name = 'regtest'
    headers_class = UnvalidatedHeaders
    pubkey_address_prefix = int2byte(111)
    script_address_prefix = int2byte(196)
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')

    max_target = 0x7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '6e3fcf1299d4ec5d79c3a4c91d624a4acf9e2e173d95a1a0504f677669687556'
    genesis_bits = 0x207fffff
    target_timespan = 1
