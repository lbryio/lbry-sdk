///
//  Generated code. Do not modify.
//  source: result.proto
///
// ignore_for_file: camel_case_types,non_constant_identifier_names,library_prefixes,unused_import,unused_shown_name,return_of_invalid_type

import 'dart:core' as $core show bool, Deprecated, double, int, List, Map, override, pragma, String;

import 'package:fixnum/fixnum.dart';
import 'package:protobuf/protobuf.dart' as $pb;

import 'result.pbenum.dart';

export 'result.pbenum.dart';

class Outputs extends $pb.GeneratedMessage {
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('Outputs', package: const $pb.PackageName('pb'))
    ..pc<Output>(1, 'txos', $pb.PbFieldType.PM,Output.create)
    ..pc<Output>(2, 'extraTxos', $pb.PbFieldType.PM,Output.create)
    ..a<$core.int>(3, 'total', $pb.PbFieldType.OU3)
    ..a<$core.int>(4, 'offset', $pb.PbFieldType.OU3)
    ..hasRequiredFields = false
  ;

  Outputs._() : super();
  factory Outputs() => create();
  factory Outputs.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory Outputs.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  Outputs clone() => Outputs()..mergeFromMessage(this);
  Outputs copyWith(void Function(Outputs) updates) => super.copyWith((message) => updates(message as Outputs));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static Outputs create() => Outputs._();
  Outputs createEmptyInstance() => create();
  static $pb.PbList<Outputs> createRepeated() => $pb.PbList<Outputs>();
  static Outputs getDefault() => _defaultInstance ??= create()..freeze();
  static Outputs _defaultInstance;

  $core.List<Output> get txos => $_getList(0);

  $core.List<Output> get extraTxos => $_getList(1);

  $core.int get total => $_get(2, 0);
  set total($core.int v) { $_setUnsignedInt32(2, v); }
  $core.bool hasTotal() => $_has(2);
  void clearTotal() => clearField(3);

  $core.int get offset => $_get(3, 0);
  set offset($core.int v) { $_setUnsignedInt32(3, v); }
  $core.bool hasOffset() => $_has(3);
  void clearOffset() => clearField(4);
}

enum Output_Meta {
  claim, 
  error, 
  notSet
}

class Output extends $pb.GeneratedMessage {
  static const $core.Map<$core.int, Output_Meta> _Output_MetaByTag = {
    7 : Output_Meta.claim,
    15 : Output_Meta.error,
    0 : Output_Meta.notSet
  };
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('Output', package: const $pb.PackageName('pb'))
    ..oo(0, [7, 15])
    ..a<$core.List<$core.int>>(1, 'txHash', $pb.PbFieldType.OY)
    ..a<$core.int>(2, 'nout', $pb.PbFieldType.OU3)
    ..a<$core.int>(3, 'height', $pb.PbFieldType.OU3)
    ..a<ClaimMeta>(7, 'claim', $pb.PbFieldType.OM, ClaimMeta.getDefault, ClaimMeta.create)
    ..a<Error>(15, 'error', $pb.PbFieldType.OM, Error.getDefault, Error.create)
    ..hasRequiredFields = false
  ;

  Output._() : super();
  factory Output() => create();
  factory Output.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory Output.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  Output clone() => Output()..mergeFromMessage(this);
  Output copyWith(void Function(Output) updates) => super.copyWith((message) => updates(message as Output));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static Output create() => Output._();
  Output createEmptyInstance() => create();
  static $pb.PbList<Output> createRepeated() => $pb.PbList<Output>();
  static Output getDefault() => _defaultInstance ??= create()..freeze();
  static Output _defaultInstance;

  Output_Meta whichMeta() => _Output_MetaByTag[$_whichOneof(0)];
  void clearMeta() => clearField($_whichOneof(0));

  $core.List<$core.int> get txHash => $_getN(0);
  set txHash($core.List<$core.int> v) { $_setBytes(0, v); }
  $core.bool hasTxHash() => $_has(0);
  void clearTxHash() => clearField(1);

  $core.int get nout => $_get(1, 0);
  set nout($core.int v) { $_setUnsignedInt32(1, v); }
  $core.bool hasNout() => $_has(1);
  void clearNout() => clearField(2);

  $core.int get height => $_get(2, 0);
  set height($core.int v) { $_setUnsignedInt32(2, v); }
  $core.bool hasHeight() => $_has(2);
  void clearHeight() => clearField(3);

  ClaimMeta get claim => $_getN(3);
  set claim(ClaimMeta v) { setField(7, v); }
  $core.bool hasClaim() => $_has(3);
  void clearClaim() => clearField(7);

  Error get error => $_getN(4);
  set error(Error v) { setField(15, v); }
  $core.bool hasError() => $_has(4);
  void clearError() => clearField(15);
}

class ClaimMeta extends $pb.GeneratedMessage {
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('ClaimMeta', package: const $pb.PackageName('pb'))
    ..a<Output>(1, 'channel', $pb.PbFieldType.OM, Output.getDefault, Output.create)
    ..aOS(2, 'shortUrl')
    ..aOS(3, 'canonicalUrl')
    ..aOB(4, 'isControlling')
    ..a<$core.int>(5, 'takeOverHeight', $pb.PbFieldType.OU3)
    ..a<$core.int>(6, 'creationHeight', $pb.PbFieldType.OU3)
    ..a<$core.int>(7, 'activationHeight', $pb.PbFieldType.OU3)
    ..a<$core.int>(8, 'expirationHeight', $pb.PbFieldType.OU3)
    ..a<$core.int>(9, 'claimsInChannel', $pb.PbFieldType.OU3)
    ..a<Int64>(10, 'effectiveAmount', $pb.PbFieldType.OU6, Int64.ZERO)
    ..a<Int64>(11, 'supportAmount', $pb.PbFieldType.OU6, Int64.ZERO)
    ..a<$core.int>(12, 'trendingGroup', $pb.PbFieldType.OU3)
    ..a<$core.double>(13, 'trendingMixed', $pb.PbFieldType.OF)
    ..a<$core.double>(14, 'trendingLocal', $pb.PbFieldType.OF)
    ..a<$core.double>(15, 'trendingGlobal', $pb.PbFieldType.OF)
    ..hasRequiredFields = false
  ;

  ClaimMeta._() : super();
  factory ClaimMeta() => create();
  factory ClaimMeta.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory ClaimMeta.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  ClaimMeta clone() => ClaimMeta()..mergeFromMessage(this);
  ClaimMeta copyWith(void Function(ClaimMeta) updates) => super.copyWith((message) => updates(message as ClaimMeta));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static ClaimMeta create() => ClaimMeta._();
  ClaimMeta createEmptyInstance() => create();
  static $pb.PbList<ClaimMeta> createRepeated() => $pb.PbList<ClaimMeta>();
  static ClaimMeta getDefault() => _defaultInstance ??= create()..freeze();
  static ClaimMeta _defaultInstance;

  Output get channel => $_getN(0);
  set channel(Output v) { setField(1, v); }
  $core.bool hasChannel() => $_has(0);
  void clearChannel() => clearField(1);

  $core.String get shortUrl => $_getS(1, '');
  set shortUrl($core.String v) { $_setString(1, v); }
  $core.bool hasShortUrl() => $_has(1);
  void clearShortUrl() => clearField(2);

  $core.String get canonicalUrl => $_getS(2, '');
  set canonicalUrl($core.String v) { $_setString(2, v); }
  $core.bool hasCanonicalUrl() => $_has(2);
  void clearCanonicalUrl() => clearField(3);

  $core.bool get isControlling => $_get(3, false);
  set isControlling($core.bool v) { $_setBool(3, v); }
  $core.bool hasIsControlling() => $_has(3);
  void clearIsControlling() => clearField(4);

  $core.int get takeOverHeight => $_get(4, 0);
  set takeOverHeight($core.int v) { $_setUnsignedInt32(4, v); }
  $core.bool hasTakeOverHeight() => $_has(4);
  void clearTakeOverHeight() => clearField(5);

  $core.int get creationHeight => $_get(5, 0);
  set creationHeight($core.int v) { $_setUnsignedInt32(5, v); }
  $core.bool hasCreationHeight() => $_has(5);
  void clearCreationHeight() => clearField(6);

  $core.int get activationHeight => $_get(6, 0);
  set activationHeight($core.int v) { $_setUnsignedInt32(6, v); }
  $core.bool hasActivationHeight() => $_has(6);
  void clearActivationHeight() => clearField(7);

  $core.int get expirationHeight => $_get(7, 0);
  set expirationHeight($core.int v) { $_setUnsignedInt32(7, v); }
  $core.bool hasExpirationHeight() => $_has(7);
  void clearExpirationHeight() => clearField(8);

  $core.int get claimsInChannel => $_get(8, 0);
  set claimsInChannel($core.int v) { $_setUnsignedInt32(8, v); }
  $core.bool hasClaimsInChannel() => $_has(8);
  void clearClaimsInChannel() => clearField(9);

  Int64 get effectiveAmount => $_getI64(9);
  set effectiveAmount(Int64 v) { $_setInt64(9, v); }
  $core.bool hasEffectiveAmount() => $_has(9);
  void clearEffectiveAmount() => clearField(10);

  Int64 get supportAmount => $_getI64(10);
  set supportAmount(Int64 v) { $_setInt64(10, v); }
  $core.bool hasSupportAmount() => $_has(10);
  void clearSupportAmount() => clearField(11);

  $core.int get trendingGroup => $_get(11, 0);
  set trendingGroup($core.int v) { $_setUnsignedInt32(11, v); }
  $core.bool hasTrendingGroup() => $_has(11);
  void clearTrendingGroup() => clearField(12);

  $core.double get trendingMixed => $_getN(12);
  set trendingMixed($core.double v) { $_setFloat(12, v); }
  $core.bool hasTrendingMixed() => $_has(12);
  void clearTrendingMixed() => clearField(13);

  $core.double get trendingLocal => $_getN(13);
  set trendingLocal($core.double v) { $_setFloat(13, v); }
  $core.bool hasTrendingLocal() => $_has(13);
  void clearTrendingLocal() => clearField(14);

  $core.double get trendingGlobal => $_getN(14);
  set trendingGlobal($core.double v) { $_setFloat(14, v); }
  $core.bool hasTrendingGlobal() => $_has(14);
  void clearTrendingGlobal() => clearField(15);
}

class Error extends $pb.GeneratedMessage {
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('Error', package: const $pb.PackageName('pb'))
    ..e<Error_Code>(1, 'code', $pb.PbFieldType.OE, Error_Code.UNKNOWN_CODE, Error_Code.valueOf, Error_Code.values)
    ..aOS(2, 'text')
    ..hasRequiredFields = false
  ;

  Error._() : super();
  factory Error() => create();
  factory Error.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory Error.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  Error clone() => Error()..mergeFromMessage(this);
  Error copyWith(void Function(Error) updates) => super.copyWith((message) => updates(message as Error));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static Error create() => Error._();
  Error createEmptyInstance() => create();
  static $pb.PbList<Error> createRepeated() => $pb.PbList<Error>();
  static Error getDefault() => _defaultInstance ??= create()..freeze();
  static Error _defaultInstance;

  Error_Code get code => $_getN(0);
  set code(Error_Code v) { setField(1, v); }
  $core.bool hasCode() => $_has(0);
  void clearCode() => clearField(1);

  $core.String get text => $_getS(1, '');
  set text($core.String v) { $_setString(1, v); }
  $core.bool hasText() => $_has(1);
  void clearText() => clearField(2);
}

