import unittest

from lbrynet.daemon.Daemon import sort_claim_results


class ClaimsComparatorTest(unittest.TestCase):
    def test_sort_claim_results_when_sorted_by_claim_id(self):
        results = [{"height": 1, "name": "res", "claim_id": "ccc", "nout": 0, "txid": "fdsafa"},
                   {"height": 1, "name": "res", "claim_id": "aaa", "nout": 0, "txid": "w5tv8uorgt"},
                   {"height": 1, "name": "res", "claim_id": "bbb", "nout": 0, "txid": "aecfaewcfa"}]
        self.run_test(results, 'claim_id', ['aaa', 'bbb', 'ccc'])

    def test_sort_claim_results_when_sorted_by_height(self):
        results = [{"height": 1, "name": "res", "claim_id": "ccc", "nout": 0, "txid": "aecfaewcfa"},
                   {"height": 3, "name": "res", "claim_id": "ccc", "nout": 0, "txid": "aecfaewcfa"},
                   {"height": 2, "name": "res", "claim_id": "ccc", "nout": 0, "txid": "aecfaewcfa"}]
        self.run_test(results, 'height', [1, 2, 3])

    def test_sort_claim_results_when_sorted_by_name(self):
        results = [{"height": 1, "name": "res1", "claim_id": "ccc", "nout": 0, "txid": "aecfaewcfa"},
                   {"height": 1, "name": "res3", "claim_id": "ccc", "nout": 0, "txid": "aecfaewcfa"},
                   {"height": 1, "name": "res2", "claim_id": "ccc", "nout": 0, "txid": "aecfaewcfa"}]
        self.run_test(results, 'name', ['res1', 'res2', 'res3'])

    def test_sort_claim_results_when_sorted_by_txid(self):
        results = [{"height": 1, "name": "res1", "claim_id": "ccc", "nout": 2, "txid": "111"},
                   {"height": 1, "name": "res1", "claim_id": "ccc", "nout": 1, "txid": "222"},
                   {"height": 1, "name": "res1", "claim_id": "ccc", "nout": 3, "txid": "333"}]
        self.run_test(results, 'txid', ['111', '222', '333'])

    def test_sort_claim_results_when_sorted_by_nout(self):
        results = [{"height": 1, "name": "res1", "claim_id": "ccc", "nout": 2, "txid": "aecfaewcfa"},
                   {"height": 1, "name": "res1", "claim_id": "ccc", "nout": 1, "txid": "aecfaewcfa"},
                   {"height": 1, "name": "res1", "claim_id": "ccc", "nout": 3, "txid": "aecfaewcfa"}]
        self.run_test(results, 'nout', [1, 2, 3])

    def run_test(self, results, field, expected):
        data = {'result': results}
        claims = sort_claim_results([data])
        claim = claims[0]
        actual = claim['result']
        self.assertEqual(expected, [r[field] for r in actual])


if __name__ == '__main__':
    unittest.main()
