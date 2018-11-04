import docopt
from twisted.trial import unittest
from lbrynet.extras.daemon.Daemon import Daemon


class DaemonDocsTests(unittest.TestCase):
    def test_can_parse_api_method_docs(self):
        failures = []
        for name, fn in Daemon.callable_methods.items():
            try:
                docopt.docopt(fn.__doc__, ())
            except docopt.DocoptLanguageError as err:
                failures.append(f"invalid docstring for {name}, {err.message}")
            except docopt.DocoptExit:
                pass
        if failures:
            self.fail("\n" + "\n".join(failures))
