VER_001 = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'LBRY fee schema 0.0.1',
    'type': 'object',

    'properties': {
        'amount': {
            'type': 'number',
            'minimum': 0,
            'exclusiveMinimum': True,
        },
        'address': {
            'type': 'string'
        }
    },
}
