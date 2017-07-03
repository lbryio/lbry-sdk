from twisted.trial import unittest
from lbrynet.daemon import DaemonCLI


class DaemonCLITests(unittest.TestCase):
    def test_guess_type(self):
        self.assertEqual('0.3.8', DaemonCLI.guess_type('0.3.8'))
        self.assertEqual(0.3, DaemonCLI.guess_type('0.3'))
        self.assertEqual(3, DaemonCLI.guess_type('3'))
        self.assertEqual('3', DaemonCLI.guess_type('3', key="uri"))
        self.assertEqual('VdNmakxFORPSyfCprAD/eDDPk5TY9QYtSA==', DaemonCLI.guess_type('VdNmakxFORPSyfCprAD/eDDPk5TY9QYtSA=='))
        self.assertEqual(0.3, DaemonCLI.guess_type('0.3'))
        self.assertEqual(True, DaemonCLI.guess_type('TRUE'))
        self.assertEqual(True, DaemonCLI.guess_type('true'))
        self.assertEqual(True, DaemonCLI.guess_type('True'))
        self.assertEqual(False, DaemonCLI.guess_type('FALSE'))
        self.assertEqual(False, DaemonCLI.guess_type('false'))
        self.assertEqual(False, DaemonCLI.guess_type('False'))
