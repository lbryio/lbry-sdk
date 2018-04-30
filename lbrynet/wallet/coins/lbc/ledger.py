from lbrynet.wallet.baseledger import BaseLedger

from .network import Network


class LBCLedger(BaseLedger):
    network_class = Network
    header_size = 112
    max_target = 0x0000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '9c89283ba0f3227f6c03b70216b9f665f0118d5e0fa729cedf4fb34d6a34f463'
    genesis_bits = 0x1f00ffff
    target_timespan = 150


class MainNetLedger(LBCLedger):
    pass


class TestNetLedger(LBCLedger):
    pass


class RegTestLedger(LBCLedger):
    max_target = 0x7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '6e3fcf1299d4ec5d79c3a4c91d624a4acf9e2e173d95a1a0504f677669687556'
    genesis_bits = 0x207fffff
    target_timespan = 1
    verify_bits_to_target = False
