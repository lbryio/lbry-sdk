MAX_QUERY_VARIABLES = 900

TXO_TYPES = {
    "other": 0,
    "stream": 1,
    "channel": 2,
    "support": 3,
    "purchase": 4,
    "collection": 5,
    "repost": 6,
}

CLAIM_TYPE_NAMES = [
    'stream',
    'channel',
    'collection',
    'repost',
]

CONTENT_TYPE_NAMES = [
    name for name in CLAIM_TYPE_NAMES if name != "channel"
]

CLAIM_TYPE_CODES = [
    TXO_TYPES[name] for name in CLAIM_TYPE_NAMES
]

CONTENT_TYPE_CODES = [
    TXO_TYPES[name] for name in CONTENT_TYPE_NAMES
]

SPENDABLE_TYPE_CODES = [
    TXO_TYPES['other'],
    TXO_TYPES['purchase']
]

STREAM_TYPES = {
    'video': 1,
    'audio': 2,
    'image': 3,
    'document': 4,
    'binary': 5,
    'model': 6
}

MATURE_TAGS = (
    'nsfw', 'porn', 'xxx', 'mature', 'adult', 'sex'
)

ATTRIBUTE_ARRAY_MAX_LENGTH = 100

SEARCH_INTEGER_PARAMS = {
    'height', 'creation_height', 'activation_height', 'expiration_height',
    'timestamp', 'creation_timestamp', 'duration', 'release_time', 'fee_amount',
    'tx_position', 'channel_join', 'reposted',
    'amount', 'staked_amount', 'support_amount',
    'trending_group', 'trending_mixed',
    'trending_local', 'trending_global',
}

SEARCH_PARAMS = {
    'name', 'text', 'claim_id', 'claim_ids', 'txid', 'nout', 'channel', 'channel_ids', 'not_channel_ids',
    'public_key_id', 'claim_type', 'stream_types', 'media_types', 'fee_currency',
    'has_channel_signature', 'signature_valid',
    'any_tags', 'all_tags', 'not_tags', 'reposted_claim_id',
    'any_locations', 'all_locations', 'not_locations',
    'any_languages', 'all_languages', 'not_languages',
    'is_controlling', 'limit', 'offset', 'order_by',
    'no_totals',
} | SEARCH_INTEGER_PARAMS

SEARCH_ORDER_FIELDS = {
    'name', 'claim_hash', 'claim_id'
} | SEARCH_INTEGER_PARAMS
