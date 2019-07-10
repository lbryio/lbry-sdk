///
//  Generated code. Do not modify.
//  source: result.proto
///
// ignore_for_file: camel_case_types,non_constant_identifier_names,library_prefixes,unused_import,unused_shown_name,return_of_invalid_type

const Outputs$json = const {
  '1': 'Outputs',
  '2': const [
    const {'1': 'txos', '3': 1, '4': 3, '5': 11, '6': '.pb.Output', '10': 'txos'},
    const {'1': 'extra_txos', '3': 2, '4': 3, '5': 11, '6': '.pb.Output', '10': 'extraTxos'},
    const {'1': 'total', '3': 3, '4': 1, '5': 13, '10': 'total'},
    const {'1': 'offset', '3': 4, '4': 1, '5': 13, '10': 'offset'},
  ],
};

const Output$json = const {
  '1': 'Output',
  '2': const [
    const {'1': 'tx_hash', '3': 1, '4': 1, '5': 12, '10': 'txHash'},
    const {'1': 'nout', '3': 2, '4': 1, '5': 13, '10': 'nout'},
    const {'1': 'height', '3': 3, '4': 1, '5': 13, '10': 'height'},
    const {'1': 'claim', '3': 7, '4': 1, '5': 11, '6': '.pb.ClaimMeta', '9': 0, '10': 'claim'},
    const {'1': 'error', '3': 15, '4': 1, '5': 11, '6': '.pb.Error', '9': 0, '10': 'error'},
  ],
  '8': const [
    const {'1': 'meta'},
  ],
};

const ClaimMeta$json = const {
  '1': 'ClaimMeta',
  '2': const [
    const {'1': 'channel', '3': 1, '4': 1, '5': 11, '6': '.pb.Output', '10': 'channel'},
    const {'1': 'short_url', '3': 2, '4': 1, '5': 9, '10': 'shortUrl'},
    const {'1': 'canonical_url', '3': 3, '4': 1, '5': 9, '10': 'canonicalUrl'},
    const {'1': 'is_controlling', '3': 4, '4': 1, '5': 8, '10': 'isControlling'},
    const {'1': 'take_over_height', '3': 5, '4': 1, '5': 13, '10': 'takeOverHeight'},
    const {'1': 'creation_height', '3': 6, '4': 1, '5': 13, '10': 'creationHeight'},
    const {'1': 'activation_height', '3': 7, '4': 1, '5': 13, '10': 'activationHeight'},
    const {'1': 'expiration_height', '3': 8, '4': 1, '5': 13, '10': 'expirationHeight'},
    const {'1': 'claims_in_channel', '3': 9, '4': 1, '5': 13, '10': 'claimsInChannel'},
    const {'1': 'effective_amount', '3': 10, '4': 1, '5': 4, '10': 'effectiveAmount'},
    const {'1': 'support_amount', '3': 11, '4': 1, '5': 4, '10': 'supportAmount'},
    const {'1': 'trending_group', '3': 12, '4': 1, '5': 13, '10': 'trendingGroup'},
    const {'1': 'trending_mixed', '3': 13, '4': 1, '5': 2, '10': 'trendingMixed'},
    const {'1': 'trending_local', '3': 14, '4': 1, '5': 2, '10': 'trendingLocal'},
    const {'1': 'trending_global', '3': 15, '4': 1, '5': 2, '10': 'trendingGlobal'},
  ],
};

const Error$json = const {
  '1': 'Error',
  '2': const [
    const {'1': 'code', '3': 1, '4': 1, '5': 14, '6': '.pb.Error.Code', '10': 'code'},
    const {'1': 'text', '3': 2, '4': 1, '5': 9, '10': 'text'},
  ],
  '4': const [Error_Code$json],
};

const Error_Code$json = const {
  '1': 'Code',
  '2': const [
    const {'1': 'UNKNOWN_CODE', '2': 0},
    const {'1': 'NOT_FOUND', '2': 1},
    const {'1': 'INVALID', '2': 2},
  ],
};

