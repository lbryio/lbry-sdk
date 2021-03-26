INDEX_DEFAULT_SETTINGS = {
    "settings":
        {"analysis":
            {"analyzer": {
                "default": {"tokenizer": "whitespace", "filter": ["lowercase", "porter_stem"]}}},
            "index":
                {"refresh_interval": -1,
                 "number_of_shards": 1,
                 "number_of_replicas": 0,
                 "sort": {
                     "field": ["trending_mixed", "release_time"],
                     "order": ["desc", "desc"]
                 }}
        },
    "mappings": {
        "properties": {
            "claim_id": {
                "fields": {
                    "keyword": {
                        "ignore_above": 256,
                        "type": "keyword"
                    }
                },
                "type": "text",
                "index_prefixes": {
                    "min_chars": 1,
                    "max_chars": 10
                }
            },
            "height": {"type": "integer"},
            "claim_type": {"type": "byte"},
            "censor_type": {"type": "byte"},
            "trending_mixed": {"type": "float"},
            "release_time": {"type": "long"},
        }
    }
}
FIELDS = {'is_controlling', 'last_take_over_height', 'claim_id', 'claim_name', 'normalized', 'tx_position', 'amount',
          'timestamp', 'creation_timestamp', 'height', 'creation_height', 'activation_height', 'expiration_height',
          'release_time', 'short_url', 'canonical_url', 'title', 'author', 'description', 'claim_type', 'reposted',
          'stream_type', 'media_type', 'fee_amount', 'fee_currency', 'duration', 'reposted_claim_hash', 'censor_type',
          'claims_in_channel', 'channel_join', 'signature_valid', 'effective_amount', 'support_amount',
          'trending_group', 'trending_mixed', 'trending_local', 'trending_global', 'channel_id', 'tx_id', 'tx_nout',
          'signature', 'signature_digest', 'public_key_bytes', 'public_key_hash', 'public_key_id', '_id', 'tags',
          'reposted_claim_id'}
TEXT_FIELDS = {'author', 'canonical_url', 'channel_id', 'claim_name', 'description', 'claim_id',
               'media_type', 'normalized', 'public_key_bytes', 'public_key_hash', 'short_url', 'signature',
               'signature_digest', 'stream_type', 'title', 'tx_id', 'fee_currency', 'reposted_claim_id', 'tags'}
RANGE_FIELDS = {
    'height', 'creation_height', 'activation_height', 'expiration_height',
    'timestamp', 'creation_timestamp', 'duration', 'release_time', 'fee_amount',
    'tx_position', 'channel_join', 'reposted', 'limit_claims_per_channel',
    'amount', 'effective_amount', 'support_amount',
    'trending_group', 'trending_mixed', 'censor_type',
    'trending_local', 'trending_global',
}
REPLACEMENTS = {
    'name': 'normalized',
    'txid': 'tx_id',
    'claim_hash': '_id'
}
