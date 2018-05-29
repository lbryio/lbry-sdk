from twisted.trial import unittest
from dht_test_environment import TestKademliaBase


class TestKademliaBootstrap(TestKademliaBase):
    """
    Test initializing the network / connecting the seed nodes
    """

    def test_bootstrap_seed_nodes(self):
        pass


@unittest.SkipTest
class TestKademliaBootstrap40Nodes(TestKademliaBase):
    network_size = 40

    def test_bootstrap_network(self):
        pass


class TestKademliaBootstrap80Nodes(TestKademliaBase):
    network_size = 80

    def test_bootstrap_network(self):
        pass


@unittest.SkipTest
class TestKademliaBootstrap120Nodes(TestKademliaBase):
    network_size = 120

    def test_bootstrap_network(self):
        pass
