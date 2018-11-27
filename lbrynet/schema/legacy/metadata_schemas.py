VER_001 = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'LBRY metadata schema 0.0.1',
    'definitions': {
        'fee_info': {
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
    },
    'type': 'object',

    'properties': {
        'ver': {
            'type': 'string',
            'default': '0.0.1'
        },
        'title': {
            'type': 'string'
        },
        'description': {
            'type': 'string'
        },
        'author': {
            'type': 'string'
        },
        'language': {
            'type': 'string'
        },
        'license': {
            'type': 'string'
        },
        'content-type': {
            'type': 'string'
        },
        'sources': {
            'type': 'object',
            'properties': {
                'lbry_sd_hash': {
                    'type': 'string'
                },
                'btih': {
                    'type': 'string'
                },
                'url': {
                    'type': 'string'
                }
            },
            'additionalProperties': False
        },
        'thumbnail': {
            'type': 'string'
        },
        'preview': {
            'type': 'string'
        },
        'fee': {
            'properties': {
                'LBC': {'$ref': '#/definitions/fee_info'},
                'BTC': {'$ref': '#/definitions/fee_info'},
                'USD': {'$ref': '#/definitions/fee_info'}
            }
        },
        'contact': {
            'type': 'number'
        },
        'pubkey': {
            'type': 'string'
        },
    },
    'required': [
        'title', 'description', 'author', 'language', 'license', 'content-type', 'sources'],
    'additionalProperties': False
}


VER_002 = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'LBRY metadata schema 0.0.2',
    'definitions': {
        'fee_info': {
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
    },
    'type': 'object',

    'properties': {
        'ver': {
            'type': 'string',
            'enum': ['0.0.2'],
        },
        'title': {
            'type': 'string'
        },
        'description': {
            'type': 'string'
        },
        'author': {
            'type': 'string'
        },
        'language': {
            'type': 'string'
        },
        'license': {
            'type': 'string'
        },
        'content-type': {
            'type': 'string'
        },
        'sources': {
            'type': 'object',
            'properties': {
                'lbry_sd_hash': {
                    'type': 'string'
                },
                'btih': {
                    'type': 'string'
                },
                'url': {
                    'type': 'string'
                }
            },
            'additionalProperties': False
        },
        'thumbnail': {
            'type': 'string'
        },
        'preview': {
            'type': 'string'
        },
        'fee': {
            'properties': {
                'LBC': {'$ref': '#/definitions/fee_info'},
                'BTC': {'$ref': '#/definitions/fee_info'},
                'USD': {'$ref': '#/definitions/fee_info'}
            }
        },
        'contact': {
            'type': 'number'
        },
        'pubkey': {
            'type': 'string'
        },
        'license_url': {
            'type': 'string'
        },
        'nsfw': {
            'type': 'boolean',
            'default': False
        },

    },
    'required': [
        'ver', 'title', 'description', 'author', 'language', 'license',
        'content-type', 'sources', 'nsfw'
    ],
    'additionalProperties': False
}


VER_003 = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'LBRY metadata schema 0.0.3',
    'definitions': {
        'fee_info': {
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
    },
    'type': 'object',

    'properties': {
        'ver': {
            'type': 'string',
            'enum': ['0.0.3'],
        },
        'title': {
            'type': 'string'
        },
        'description': {
            'type': 'string'
        },
        'author': {
            'type': 'string'
        },
        'language': {
            'type': 'string'
        },
        'license': {
            'type': 'string'
        },
        'content_type': {
            'type': 'string'
        },
        'sources': {
            'type': 'object',
            'properties': {
                'lbry_sd_hash': {
                    'type': 'string'
                },
                'btih': {
                    'type': 'string'
                },
                'url': {
                    'type': 'string'
                }
            },
            'additionalProperties': False
        },
        'thumbnail': {
            'type': 'string'
        },
        'preview': {
            'type': 'string'
        },
        'fee': {
            'properties': {
                'LBC': {'$ref': '#/definitions/fee_info'},
                'BTC': {'$ref': '#/definitions/fee_info'},
                'USD': {'$ref': '#/definitions/fee_info'}
            }
        },
        'contact': {
            'type': 'number'
        },
        'pubkey': {
            'type': 'string'
        },
        'license_url': {
            'type': 'string'
        },
        'nsfw': {
            'type': 'boolean',
            'default': False
        },
        'sig': {
            'type': 'string'
        }
    },
    'required': [
        'ver', 'title', 'description', 'author', 'language', 'license',
        'content_type', 'sources', 'nsfw'
    ],
    'additionalProperties': False,
    'dependencies': {
        'pubkey': ['sig'],
        'sig': ['pubkey']
    }
}
