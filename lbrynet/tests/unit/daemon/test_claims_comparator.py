import unittest

from lbrynet.daemon.claims_comparator import arrange_results


class ClaimsComparatorTest(unittest.TestCase):
    def test_arrange_results(self):
        results = [
            {
                'height': 1,
                'name': 'res',
                'claim_id': 'ccc'
            },
            {
                'height': 1,
                'name': 'res',
                'claim_id': 'aaa'
            },
            {
                'height': 1,
                'name': 'res',
                'claim_id': 'bbb'
            }
        ]
        data = {'result': results}

        expected = [
            {
                'height': 1,
                'name': 'res',
                'claim_id': 'aaa'
            },
            {
                'height': 1,
                'name': 'res',
                'claim_id': 'bbb'
            },
            {
                'height': 1,
                'name': 'res',
                'claim_id': 'ccc'
            }
        ]
        claims = arrange_results([data])
        claim = claims[0]
        actual = claim['result']

        self.assertEqual(expected, actual)


if __name__ == '__main__':
    unittest.main()
