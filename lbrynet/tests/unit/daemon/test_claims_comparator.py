import json
import unittest

from lbrynet.daemon.claims_comparator import arrange_results


class ClaimsComparatorTest(unittest.TestCase):
    def setUp(self):
        with open('claims_comparator_cases.json') as f:
            document = json.load(f)
        self.cases = document['cases']

    def test_arrange_results(self):
        for case in self.cases:
            results = case['results']
            data = {'result': results}
            expected = case['expected']

            claims = arrange_results([data])
            claim = claims[0]
            actual = claim['result']

            self.assertEqual(expected, actual, case['description'])


if __name__ == '__main__':
    unittest.main()
