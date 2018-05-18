import unittest

from lbrynet.daemon.Daemon import arrange_results


class ClaimsComparatorTest(unittest.TestCase):
    def test_arrange_results_when_sorted_by_claim_id(self):
        self.run_test(
            [
                {
                    "height": 1,
                    "name": "res",
                    "claim_id": "ccc",
                    "nout": 0,
                    "txid": "fdsafa"
                },
                {
                    "height": 1,
                    "name": "res",
                    "claim_id": "aaa",
                    "nout": 0,
                    "txid": "w5tv8uorgt"
                },
                {
                    "height": 1,
                    "name": "res",
                    "claim_id": "bbb",
                    "nout": 0,
                    "txid": "aecfaewcfa"
                }
            ],
            [
                {
                    "height": 1,
                    "name": "res",
                    "claim_id": "aaa",
                    "nout": 0,
                    "txid": "w5tv8uorgt"
                },
                {
                    "height": 1,
                    "name": "res",
                    "claim_id": "bbb",
                    "nout": 0,
                    "txid": "aecfaewcfa"
                },
                {
                    "height": 1,
                    "name": "res",
                    "claim_id": "ccc",
                    "nout": 0,
                    "txid": "fdsafa"
                }
            ])

    def test_arrange_results_when_sorted_by_height(self):
        self.run_test(
            [
                {
                    "height": 1,
                    "name": "res",
                    "claim_id": "ccc",
                    "nout": 0,
                    "txid": "aecfaewcfa"
                },
                {
                    "height": 3,
                    "name": "res",
                    "claim_id": "ccc",
                    "nout": 0,
                    "txid": "aecfaewcfa"
                },
                {
                    "height": 2,
                    "name": "res",
                    "claim_id": "ccc",
                    "nout": 0,
                    "txid": "aecfaewcfa"
                }
            ],
            [
                {
                    "claim_id": "ccc",
                    "height": 1,
                    "name": "res",
                    "nout": 0,
                    "txid": "aecfaewcfa"
                },
                {
                    "claim_id": "ccc",
                    "height": 2,
                    "name": "res",
                    "nout": 0,
                    "txid": "aecfaewcfa"
                },
                {
                    "claim_id": "ccc",
                    "height": 3,
                    "name": "res",
                    "nout": 0,
                    "txid": "aecfaewcfa"
                }
            ])

    def test_arrange_results_when_sorted_by_name(self):
        self.run_test(
            [
                {
                    "height": 1,
                    "name": "res1",
                    "claim_id": "ccc",
                    "nout": 0,
                    "txid": "aecfaewcfa"
                },
                {
                    "height": 1,
                    "name": "res3",
                    "claim_id": "ccc",
                    "nout": 0,
                    "txid": "aecfaewcfa"
                },
                {
                    "height": 1,
                    "name": "res2",
                    "claim_id": "ccc",
                    "nout": 0,
                    "txid": "aecfaewcfa"
                }
            ],
            [
                {
                    "height": 1,
                    "name": "res1",
                    "claim_id": "ccc",
                    "nout": 0,
                    "txid": "aecfaewcfa"
                },
                {
                    "height": 1,
                    "name": "res2",
                    "claim_id": "ccc",
                    "nout": 0,
                    "txid": "aecfaewcfa"
                },
                {
                    "height": 1,
                    "name": "res3",
                    "claim_id": "ccc",
                    "nout": 0,
                    "txid": "aecfaewcfa"
                }
            ])

    def test_arrange_results_when_sort_by_outpoint(self):
        self.run_test(
            [
                {
                    "height": 1,
                    "name": "res1",
                    "claim_id": "ccc",
                    "nout": 2,
                    "txid": "aecfaewcfa"
                },
                {
                    "height": 1,
                    "name": "res1",
                    "claim_id": "ccc",
                    "nout": 1,
                    "txid": "aecfaewcfa"
                },
                {
                    "height": 1,
                    "name": "res1",
                    "claim_id": "ccc",
                    "nout": 3,
                    "txid": "aecfaewcfa"
                }
            ],
            [
                {
                    "height": 1,
                    "name": "res1",
                    "claim_id": "ccc",
                    "nout": 1,
                    "txid": "aecfaewcfa"
                },
                {
                    "height": 1,
                    "name": "res1",
                    "claim_id": "ccc",
                    "nout": 2,
                    "txid": "aecfaewcfa"
                },
                {
                    "height": 1,
                    "name": "res1",
                    "claim_id": "ccc",
                    "nout": 3,
                    "txid": "aecfaewcfa"
                }
            ])

    def run_test(self, results, expected):
        data = {'result': results}

        claims = arrange_results([data])
        claim = claims[0]
        actual = claim['result']

        self.assertEqual(expected, actual)


if __name__ == '__main__':
    unittest.main()
