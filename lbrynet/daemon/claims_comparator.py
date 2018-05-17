def arrange_results(claims):
    for claim in claims:
        results = claim['result']
        sorted_results = sorted(results, key=lambda d: (d['height'], d['name'], d['claim_id'], _outpoint(d)))
        claim['result'] = sorted_results
    return claims


def _outpoint(claim):
    return '{}:{}'.format(claim['txid'], claim['nout'])
