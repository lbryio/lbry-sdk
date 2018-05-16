_comparison_order = ['height', 'name', 'claim_id']  # TODO outpoint


def arrange_results(claims):
    for claim in claims:
        results = claim['result']
        sorted_results = sorted(results, cmp=_compare_results)
        claim['result'] = sorted_results
    return claims


def _compare_results(left, right):
    """
    :type left: dict
    :type right: dict
    """
    result = 0

    for attribute in _comparison_order:
        left_value = left[attribute]
        right_value = right[attribute]
        sub_result = _cmp(left_value, right_value)
        if sub_result is not 0:
            result = sub_result
            break

    return result


def _cmp(left, right):
    if left == right:
        return 0
    elif left < right:
        return -1
    else:
        return 1
