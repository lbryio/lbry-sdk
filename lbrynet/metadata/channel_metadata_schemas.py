VER_001 = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'LBRY channel metadata schema 0.0.1',

    'type': 'object',

    'properties': {
        'ver': {
            'type': 'string',
            'enum': ['0.0.1']
        },
        'type': {
            'type': 'string',
            'enum': 'channel',
        },
        'title': {
            'type': 'string'
        },
        'description': {
            'type': 'string'
        },
        'thumbnail': {
            'type': 'string'
        },
    },
    'required': ['type', 'title', 'description', 'thumbnail'],
    'additionalProperties': False
}
