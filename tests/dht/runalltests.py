#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive

""" Wrapper script to run all included test scripts """

import os, sys
import unittest

def runTests():
    testRunner = unittest.TextTestRunner()
    testRunner.run(additional_tests())

def additional_tests():
    """ Used directly by setuptools to run unittests """
    sys.path.insert(0, os.path.dirname(__file__))
    suite = unittest.TestSuite()
    tests = os.listdir(os.path.dirname(__file__))
    tests = [n[:-3] for n in tests if n.startswith('test') and n.endswith('.py')]
    for test in tests:
        m = __import__(test)
        if hasattr(m, 'suite'):
            suite.addTest(m.suite())
    sys.path.pop(0)
    return suite

    
if __name__ == '__main__':
    # Add parent folder to sys path so it's easier to use
    sys.path.insert(0,os.path.abspath('..'))
    runTests()
