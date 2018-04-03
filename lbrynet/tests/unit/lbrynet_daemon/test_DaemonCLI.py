import docopt
from twisted.trial import unittest
from lbrynet.daemon import DaemonCLI
from lbrynet.daemon.Daemon import Daemon


class DaemonCLITests(unittest.TestCase):
    def test_guess_type(self):
        self.assertEqual('0.3.8', DaemonCLI.guess_type('0.3.8'))
        self.assertEqual(0.3, DaemonCLI.guess_type('0.3'))
        self.assertEqual(3, DaemonCLI.guess_type('3'))
        self.assertEqual('VdNmakxFORPSyfCprAD/eDDPk5TY9QYtSA==',
                         DaemonCLI.guess_type('VdNmakxFORPSyfCprAD/eDDPk5TY9QYtSA=='))
        self.assertEqual(0.3, DaemonCLI.guess_type('0.3'))
        self.assertEqual(True, DaemonCLI.guess_type('TRUE'))
        self.assertEqual(True, DaemonCLI.guess_type('true'))
        self.assertEqual(True, DaemonCLI.guess_type('True'))
        self.assertEqual(False, DaemonCLI.guess_type('FALSE'))
        self.assertEqual(False, DaemonCLI.guess_type('false'))
        self.assertEqual(False, DaemonCLI.guess_type('False'))


        self.assertEqual('3', DaemonCLI.guess_type('3', key="uri"))
        self.assertEqual('0.3', DaemonCLI.guess_type('0.3', key="uri"))
        self.assertEqual('True', DaemonCLI.guess_type('True', key="uri"))
        self.assertEqual('False', DaemonCLI.guess_type('False', key="uri"))

        self.assertEqual('3', DaemonCLI.guess_type('3', key="file_name"))
        self.assertEqual('3', DaemonCLI.guess_type('3', key="name"))
        self.assertEqual('3', DaemonCLI.guess_type('3', key="download_directory"))
        self.assertEqual('3', DaemonCLI.guess_type('3', key="channel_name"))

        self.assertEqual(3, DaemonCLI.guess_type('3', key="some_other_thing"))


class DaemonDocsTests(unittest.TestCase):
    def test_can_parse_api_method_docs(self):
        failures = []
        for name, fn in Daemon.callable_methods.iteritems():
            try:
                docopt.docopt(fn.__doc__, ())
            except docopt.DocoptLanguageError as err:
                failures.append("invalid docstring for %s, %s" % (name, err.message))
            except docopt.DocoptExit:
                pass
        if failures:
            self.fail("\n" + "\n".join(failures))
