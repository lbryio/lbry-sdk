///
//  Generated code. Do not modify.
//  source: result.proto
///
// ignore_for_file: camel_case_types,non_constant_identifier_names,library_prefixes,unused_import,unused_shown_name,return_of_invalid_type

// ignore_for_file: UNDEFINED_SHOWN_NAME,UNUSED_SHOWN_NAME
import 'dart:core' as $core show int, dynamic, String, List, Map;
import 'package:protobuf/protobuf.dart' as $pb;

class Error_Code extends $pb.ProtobufEnum {
  static const Error_Code UNKNOWN_CODE = Error_Code._(0, 'UNKNOWN_CODE');
  static const Error_Code NOT_FOUND = Error_Code._(1, 'NOT_FOUND');
  static const Error_Code INVALID = Error_Code._(2, 'INVALID');

  static const $core.List<Error_Code> values = <Error_Code> [
    UNKNOWN_CODE,
    NOT_FOUND,
    INVALID,
  ];

  static final $core.Map<$core.int, Error_Code> _byValue = $pb.ProtobufEnum.initByValue(values);
  static Error_Code valueOf($core.int value) => _byValue[value];

  const Error_Code._($core.int v, $core.String n) : super(v, n);
}

