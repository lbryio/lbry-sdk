///
//  Generated code. Do not modify.
//  source: claim.proto
///
// ignore_for_file: camel_case_types,non_constant_identifier_names,library_prefixes,unused_import,unused_shown_name,return_of_invalid_type

import 'dart:core' as $core show bool, Deprecated, double, int, List, Map, override, pragma, String;

import 'package:fixnum/fixnum.dart';
import 'package:protobuf/protobuf.dart' as $pb;

import 'claim.pbenum.dart';

export 'claim.pbenum.dart';

enum Claim_Type {
  stream, 
  channel, 
  collection, 
  repost, 
  notSet
}

class Claim extends $pb.GeneratedMessage {
  static const $core.Map<$core.int, Claim_Type> _Claim_TypeByTag = {
    1 : Claim_Type.stream,
    2 : Claim_Type.channel,
    3 : Claim_Type.collection,
    4 : Claim_Type.repost,
    0 : Claim_Type.notSet
  };
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('Claim', package: const $pb.PackageName('pb'))
    ..oo(0, [1, 2, 3, 4])
    ..a<Stream>(1, 'stream', $pb.PbFieldType.OM, Stream.getDefault, Stream.create)
    ..a<Channel>(2, 'channel', $pb.PbFieldType.OM, Channel.getDefault, Channel.create)
    ..a<ClaimList>(3, 'collection', $pb.PbFieldType.OM, ClaimList.getDefault, ClaimList.create)
    ..a<ClaimReference>(4, 'repost', $pb.PbFieldType.OM, ClaimReference.getDefault, ClaimReference.create)
    ..aOS(8, 'title')
    ..aOS(9, 'description')
    ..a<Source>(10, 'thumbnail', $pb.PbFieldType.OM, Source.getDefault, Source.create)
    ..pPS(11, 'tags')
    ..pc<Language>(12, 'languages', $pb.PbFieldType.PM,Language.create)
    ..pc<Location>(13, 'locations', $pb.PbFieldType.PM,Location.create)
    ..hasRequiredFields = false
  ;

  Claim._() : super();
  factory Claim() => create();
  factory Claim.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory Claim.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  Claim clone() => Claim()..mergeFromMessage(this);
  Claim copyWith(void Function(Claim) updates) => super.copyWith((message) => updates(message as Claim));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static Claim create() => Claim._();
  Claim createEmptyInstance() => create();
  static $pb.PbList<Claim> createRepeated() => $pb.PbList<Claim>();
  static Claim getDefault() => _defaultInstance ??= create()..freeze();
  static Claim _defaultInstance;

  Claim_Type whichType() => _Claim_TypeByTag[$_whichOneof(0)];
  void clearType() => clearField($_whichOneof(0));

  Stream get stream => $_getN(0);
  set stream(Stream v) { setField(1, v); }
  $core.bool hasStream() => $_has(0);
  void clearStream() => clearField(1);

  Channel get channel => $_getN(1);
  set channel(Channel v) { setField(2, v); }
  $core.bool hasChannel() => $_has(1);
  void clearChannel() => clearField(2);

  ClaimList get collection => $_getN(2);
  set collection(ClaimList v) { setField(3, v); }
  $core.bool hasCollection() => $_has(2);
  void clearCollection() => clearField(3);

  ClaimReference get repost => $_getN(3);
  set repost(ClaimReference v) { setField(4, v); }
  $core.bool hasRepost() => $_has(3);
  void clearRepost() => clearField(4);

  $core.String get title => $_getS(4, '');
  set title($core.String v) { $_setString(4, v); }
  $core.bool hasTitle() => $_has(4);
  void clearTitle() => clearField(8);

  $core.String get description => $_getS(5, '');
  set description($core.String v) { $_setString(5, v); }
  $core.bool hasDescription() => $_has(5);
  void clearDescription() => clearField(9);

  Source get thumbnail => $_getN(6);
  set thumbnail(Source v) { setField(10, v); }
  $core.bool hasThumbnail() => $_has(6);
  void clearThumbnail() => clearField(10);

  $core.List<$core.String> get tags => $_getList(7);

  $core.List<Language> get languages => $_getList(8);

  $core.List<Location> get locations => $_getList(9);
}

enum Stream_Type {
  image, 
  video, 
  audio, 
  software, 
  notSet
}

class Stream extends $pb.GeneratedMessage {
  static const $core.Map<$core.int, Stream_Type> _Stream_TypeByTag = {
    10 : Stream_Type.image,
    11 : Stream_Type.video,
    12 : Stream_Type.audio,
    13 : Stream_Type.software,
    0 : Stream_Type.notSet
  };
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('Stream', package: const $pb.PackageName('pb'))
    ..oo(0, [10, 11, 12, 13])
    ..a<Source>(1, 'source', $pb.PbFieldType.OM, Source.getDefault, Source.create)
    ..aOS(2, 'author')
    ..aOS(3, 'license')
    ..aOS(4, 'licenseUrl')
    ..aInt64(5, 'releaseTime')
    ..a<Fee>(6, 'fee', $pb.PbFieldType.OM, Fee.getDefault, Fee.create)
    ..a<Image>(10, 'image', $pb.PbFieldType.OM, Image.getDefault, Image.create)
    ..a<Video>(11, 'video', $pb.PbFieldType.OM, Video.getDefault, Video.create)
    ..a<Audio>(12, 'audio', $pb.PbFieldType.OM, Audio.getDefault, Audio.create)
    ..a<Software>(13, 'software', $pb.PbFieldType.OM, Software.getDefault, Software.create)
    ..hasRequiredFields = false
  ;

  Stream._() : super();
  factory Stream() => create();
  factory Stream.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory Stream.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  Stream clone() => Stream()..mergeFromMessage(this);
  Stream copyWith(void Function(Stream) updates) => super.copyWith((message) => updates(message as Stream));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static Stream create() => Stream._();
  Stream createEmptyInstance() => create();
  static $pb.PbList<Stream> createRepeated() => $pb.PbList<Stream>();
  static Stream getDefault() => _defaultInstance ??= create()..freeze();
  static Stream _defaultInstance;

  Stream_Type whichType() => _Stream_TypeByTag[$_whichOneof(0)];
  void clearType() => clearField($_whichOneof(0));

  Source get source => $_getN(0);
  set source(Source v) { setField(1, v); }
  $core.bool hasSource() => $_has(0);
  void clearSource() => clearField(1);

  $core.String get author => $_getS(1, '');
  set author($core.String v) { $_setString(1, v); }
  $core.bool hasAuthor() => $_has(1);
  void clearAuthor() => clearField(2);

  $core.String get license => $_getS(2, '');
  set license($core.String v) { $_setString(2, v); }
  $core.bool hasLicense() => $_has(2);
  void clearLicense() => clearField(3);

  $core.String get licenseUrl => $_getS(3, '');
  set licenseUrl($core.String v) { $_setString(3, v); }
  $core.bool hasLicenseUrl() => $_has(3);
  void clearLicenseUrl() => clearField(4);

  Int64 get releaseTime => $_getI64(4);
  set releaseTime(Int64 v) { $_setInt64(4, v); }
  $core.bool hasReleaseTime() => $_has(4);
  void clearReleaseTime() => clearField(5);

  Fee get fee => $_getN(5);
  set fee(Fee v) { setField(6, v); }
  $core.bool hasFee() => $_has(5);
  void clearFee() => clearField(6);

  Image get image => $_getN(6);
  set image(Image v) { setField(10, v); }
  $core.bool hasImage() => $_has(6);
  void clearImage() => clearField(10);

  Video get video => $_getN(7);
  set video(Video v) { setField(11, v); }
  $core.bool hasVideo() => $_has(7);
  void clearVideo() => clearField(11);

  Audio get audio => $_getN(8);
  set audio(Audio v) { setField(12, v); }
  $core.bool hasAudio() => $_has(8);
  void clearAudio() => clearField(12);

  Software get software => $_getN(9);
  set software(Software v) { setField(13, v); }
  $core.bool hasSoftware() => $_has(9);
  void clearSoftware() => clearField(13);
}

class Channel extends $pb.GeneratedMessage {
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('Channel', package: const $pb.PackageName('pb'))
    ..a<$core.List<$core.int>>(1, 'publicKey', $pb.PbFieldType.OY)
    ..aOS(2, 'email')
    ..aOS(3, 'websiteUrl')
    ..a<Source>(4, 'cover', $pb.PbFieldType.OM, Source.getDefault, Source.create)
    ..a<ClaimList>(5, 'featured', $pb.PbFieldType.OM, ClaimList.getDefault, ClaimList.create)
    ..hasRequiredFields = false
  ;

  Channel._() : super();
  factory Channel() => create();
  factory Channel.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory Channel.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  Channel clone() => Channel()..mergeFromMessage(this);
  Channel copyWith(void Function(Channel) updates) => super.copyWith((message) => updates(message as Channel));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static Channel create() => Channel._();
  Channel createEmptyInstance() => create();
  static $pb.PbList<Channel> createRepeated() => $pb.PbList<Channel>();
  static Channel getDefault() => _defaultInstance ??= create()..freeze();
  static Channel _defaultInstance;

  $core.List<$core.int> get publicKey => $_getN(0);
  set publicKey($core.List<$core.int> v) { $_setBytes(0, v); }
  $core.bool hasPublicKey() => $_has(0);
  void clearPublicKey() => clearField(1);

  $core.String get email => $_getS(1, '');
  set email($core.String v) { $_setString(1, v); }
  $core.bool hasEmail() => $_has(1);
  void clearEmail() => clearField(2);

  $core.String get websiteUrl => $_getS(2, '');
  set websiteUrl($core.String v) { $_setString(2, v); }
  $core.bool hasWebsiteUrl() => $_has(2);
  void clearWebsiteUrl() => clearField(3);

  Source get cover => $_getN(3);
  set cover(Source v) { setField(4, v); }
  $core.bool hasCover() => $_has(3);
  void clearCover() => clearField(4);

  ClaimList get featured => $_getN(4);
  set featured(ClaimList v) { setField(5, v); }
  $core.bool hasFeatured() => $_has(4);
  void clearFeatured() => clearField(5);
}

class ClaimReference extends $pb.GeneratedMessage {
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('ClaimReference', package: const $pb.PackageName('pb'))
    ..a<$core.List<$core.int>>(1, 'claimHash', $pb.PbFieldType.OY)
    ..hasRequiredFields = false
  ;

  ClaimReference._() : super();
  factory ClaimReference() => create();
  factory ClaimReference.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory ClaimReference.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  ClaimReference clone() => ClaimReference()..mergeFromMessage(this);
  ClaimReference copyWith(void Function(ClaimReference) updates) => super.copyWith((message) => updates(message as ClaimReference));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static ClaimReference create() => ClaimReference._();
  ClaimReference createEmptyInstance() => create();
  static $pb.PbList<ClaimReference> createRepeated() => $pb.PbList<ClaimReference>();
  static ClaimReference getDefault() => _defaultInstance ??= create()..freeze();
  static ClaimReference _defaultInstance;

  $core.List<$core.int> get claimHash => $_getN(0);
  set claimHash($core.List<$core.int> v) { $_setBytes(0, v); }
  $core.bool hasClaimHash() => $_has(0);
  void clearClaimHash() => clearField(1);
}

class ClaimList extends $pb.GeneratedMessage {
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('ClaimList', package: const $pb.PackageName('pb'))
    ..e<ClaimList_ListType>(1, 'listType', $pb.PbFieldType.OE, ClaimList_ListType.COLLECTION, ClaimList_ListType.valueOf, ClaimList_ListType.values)
    ..pc<ClaimReference>(2, 'claimReferences', $pb.PbFieldType.PM,ClaimReference.create)
    ..hasRequiredFields = false
  ;

  ClaimList._() : super();
  factory ClaimList() => create();
  factory ClaimList.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory ClaimList.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  ClaimList clone() => ClaimList()..mergeFromMessage(this);
  ClaimList copyWith(void Function(ClaimList) updates) => super.copyWith((message) => updates(message as ClaimList));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static ClaimList create() => ClaimList._();
  ClaimList createEmptyInstance() => create();
  static $pb.PbList<ClaimList> createRepeated() => $pb.PbList<ClaimList>();
  static ClaimList getDefault() => _defaultInstance ??= create()..freeze();
  static ClaimList _defaultInstance;

  ClaimList_ListType get listType => $_getN(0);
  set listType(ClaimList_ListType v) { setField(1, v); }
  $core.bool hasListType() => $_has(0);
  void clearListType() => clearField(1);

  $core.List<ClaimReference> get claimReferences => $_getList(1);
}

class Source extends $pb.GeneratedMessage {
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('Source', package: const $pb.PackageName('pb'))
    ..a<$core.List<$core.int>>(1, 'hash', $pb.PbFieldType.OY)
    ..aOS(2, 'name')
    ..a<Int64>(3, 'size', $pb.PbFieldType.OU6, Int64.ZERO)
    ..aOS(4, 'mediaType')
    ..aOS(5, 'url')
    ..a<$core.List<$core.int>>(6, 'sdHash', $pb.PbFieldType.OY)
    ..hasRequiredFields = false
  ;

  Source._() : super();
  factory Source() => create();
  factory Source.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory Source.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  Source clone() => Source()..mergeFromMessage(this);
  Source copyWith(void Function(Source) updates) => super.copyWith((message) => updates(message as Source));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static Source create() => Source._();
  Source createEmptyInstance() => create();
  static $pb.PbList<Source> createRepeated() => $pb.PbList<Source>();
  static Source getDefault() => _defaultInstance ??= create()..freeze();
  static Source _defaultInstance;

  $core.List<$core.int> get hash => $_getN(0);
  set hash($core.List<$core.int> v) { $_setBytes(0, v); }
  $core.bool hasHash() => $_has(0);
  void clearHash() => clearField(1);

  $core.String get name => $_getS(1, '');
  set name($core.String v) { $_setString(1, v); }
  $core.bool hasName() => $_has(1);
  void clearName() => clearField(2);

  Int64 get size => $_getI64(2);
  set size(Int64 v) { $_setInt64(2, v); }
  $core.bool hasSize() => $_has(2);
  void clearSize() => clearField(3);

  $core.String get mediaType => $_getS(3, '');
  set mediaType($core.String v) { $_setString(3, v); }
  $core.bool hasMediaType() => $_has(3);
  void clearMediaType() => clearField(4);

  $core.String get url => $_getS(4, '');
  set url($core.String v) { $_setString(4, v); }
  $core.bool hasUrl() => $_has(4);
  void clearUrl() => clearField(5);

  $core.List<$core.int> get sdHash => $_getN(5);
  set sdHash($core.List<$core.int> v) { $_setBytes(5, v); }
  $core.bool hasSdHash() => $_has(5);
  void clearSdHash() => clearField(6);
}

class Fee extends $pb.GeneratedMessage {
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('Fee', package: const $pb.PackageName('pb'))
    ..e<Fee_Currency>(1, 'currency', $pb.PbFieldType.OE, Fee_Currency.UNKNOWN_CURRENCY, Fee_Currency.valueOf, Fee_Currency.values)
    ..a<$core.List<$core.int>>(2, 'address', $pb.PbFieldType.OY)
    ..a<Int64>(3, 'amount', $pb.PbFieldType.OU6, Int64.ZERO)
    ..hasRequiredFields = false
  ;

  Fee._() : super();
  factory Fee() => create();
  factory Fee.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory Fee.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  Fee clone() => Fee()..mergeFromMessage(this);
  Fee copyWith(void Function(Fee) updates) => super.copyWith((message) => updates(message as Fee));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static Fee create() => Fee._();
  Fee createEmptyInstance() => create();
  static $pb.PbList<Fee> createRepeated() => $pb.PbList<Fee>();
  static Fee getDefault() => _defaultInstance ??= create()..freeze();
  static Fee _defaultInstance;

  Fee_Currency get currency => $_getN(0);
  set currency(Fee_Currency v) { setField(1, v); }
  $core.bool hasCurrency() => $_has(0);
  void clearCurrency() => clearField(1);

  $core.List<$core.int> get address => $_getN(1);
  set address($core.List<$core.int> v) { $_setBytes(1, v); }
  $core.bool hasAddress() => $_has(1);
  void clearAddress() => clearField(2);

  Int64 get amount => $_getI64(2);
  set amount(Int64 v) { $_setInt64(2, v); }
  $core.bool hasAmount() => $_has(2);
  void clearAmount() => clearField(3);
}

class Image extends $pb.GeneratedMessage {
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('Image', package: const $pb.PackageName('pb'))
    ..a<$core.int>(1, 'width', $pb.PbFieldType.OU3)
    ..a<$core.int>(2, 'height', $pb.PbFieldType.OU3)
    ..hasRequiredFields = false
  ;

  Image._() : super();
  factory Image() => create();
  factory Image.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory Image.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  Image clone() => Image()..mergeFromMessage(this);
  Image copyWith(void Function(Image) updates) => super.copyWith((message) => updates(message as Image));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static Image create() => Image._();
  Image createEmptyInstance() => create();
  static $pb.PbList<Image> createRepeated() => $pb.PbList<Image>();
  static Image getDefault() => _defaultInstance ??= create()..freeze();
  static Image _defaultInstance;

  $core.int get width => $_get(0, 0);
  set width($core.int v) { $_setUnsignedInt32(0, v); }
  $core.bool hasWidth() => $_has(0);
  void clearWidth() => clearField(1);

  $core.int get height => $_get(1, 0);
  set height($core.int v) { $_setUnsignedInt32(1, v); }
  $core.bool hasHeight() => $_has(1);
  void clearHeight() => clearField(2);
}

class Video extends $pb.GeneratedMessage {
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('Video', package: const $pb.PackageName('pb'))
    ..a<$core.int>(1, 'width', $pb.PbFieldType.OU3)
    ..a<$core.int>(2, 'height', $pb.PbFieldType.OU3)
    ..a<$core.int>(3, 'duration', $pb.PbFieldType.OU3)
    ..a<Audio>(15, 'audio', $pb.PbFieldType.OM, Audio.getDefault, Audio.create)
    ..hasRequiredFields = false
  ;

  Video._() : super();
  factory Video() => create();
  factory Video.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory Video.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  Video clone() => Video()..mergeFromMessage(this);
  Video copyWith(void Function(Video) updates) => super.copyWith((message) => updates(message as Video));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static Video create() => Video._();
  Video createEmptyInstance() => create();
  static $pb.PbList<Video> createRepeated() => $pb.PbList<Video>();
  static Video getDefault() => _defaultInstance ??= create()..freeze();
  static Video _defaultInstance;

  $core.int get width => $_get(0, 0);
  set width($core.int v) { $_setUnsignedInt32(0, v); }
  $core.bool hasWidth() => $_has(0);
  void clearWidth() => clearField(1);

  $core.int get height => $_get(1, 0);
  set height($core.int v) { $_setUnsignedInt32(1, v); }
  $core.bool hasHeight() => $_has(1);
  void clearHeight() => clearField(2);

  $core.int get duration => $_get(2, 0);
  set duration($core.int v) { $_setUnsignedInt32(2, v); }
  $core.bool hasDuration() => $_has(2);
  void clearDuration() => clearField(3);

  Audio get audio => $_getN(3);
  set audio(Audio v) { setField(15, v); }
  $core.bool hasAudio() => $_has(3);
  void clearAudio() => clearField(15);
}

class Audio extends $pb.GeneratedMessage {
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('Audio', package: const $pb.PackageName('pb'))
    ..a<$core.int>(1, 'duration', $pb.PbFieldType.OU3)
    ..hasRequiredFields = false
  ;

  Audio._() : super();
  factory Audio() => create();
  factory Audio.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory Audio.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  Audio clone() => Audio()..mergeFromMessage(this);
  Audio copyWith(void Function(Audio) updates) => super.copyWith((message) => updates(message as Audio));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static Audio create() => Audio._();
  Audio createEmptyInstance() => create();
  static $pb.PbList<Audio> createRepeated() => $pb.PbList<Audio>();
  static Audio getDefault() => _defaultInstance ??= create()..freeze();
  static Audio _defaultInstance;

  $core.int get duration => $_get(0, 0);
  set duration($core.int v) { $_setUnsignedInt32(0, v); }
  $core.bool hasDuration() => $_has(0);
  void clearDuration() => clearField(1);
}

class Software extends $pb.GeneratedMessage {
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('Software', package: const $pb.PackageName('pb'))
    ..aOS(1, 'os')
    ..hasRequiredFields = false
  ;

  Software._() : super();
  factory Software() => create();
  factory Software.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory Software.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  Software clone() => Software()..mergeFromMessage(this);
  Software copyWith(void Function(Software) updates) => super.copyWith((message) => updates(message as Software));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static Software create() => Software._();
  Software createEmptyInstance() => create();
  static $pb.PbList<Software> createRepeated() => $pb.PbList<Software>();
  static Software getDefault() => _defaultInstance ??= create()..freeze();
  static Software _defaultInstance;

  $core.String get os => $_getS(0, '');
  set os($core.String v) { $_setString(0, v); }
  $core.bool hasOs() => $_has(0);
  void clearOs() => clearField(1);
}

class Language extends $pb.GeneratedMessage {
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('Language', package: const $pb.PackageName('pb'))
    ..e<Language_Language>(1, 'language', $pb.PbFieldType.OE, Language_Language.UNKNOWN_LANGUAGE, Language_Language.valueOf, Language_Language.values)
    ..e<Language_Script>(2, 'script', $pb.PbFieldType.OE, Language_Script.UNKNOWN_SCRIPT, Language_Script.valueOf, Language_Script.values)
    ..e<Location_Country>(3, 'region', $pb.PbFieldType.OE, Location_Country.UNKNOWN_COUNTRY, Location_Country.valueOf, Location_Country.values)
    ..hasRequiredFields = false
  ;

  Language._() : super();
  factory Language() => create();
  factory Language.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory Language.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  Language clone() => Language()..mergeFromMessage(this);
  Language copyWith(void Function(Language) updates) => super.copyWith((message) => updates(message as Language));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static Language create() => Language._();
  Language createEmptyInstance() => create();
  static $pb.PbList<Language> createRepeated() => $pb.PbList<Language>();
  static Language getDefault() => _defaultInstance ??= create()..freeze();
  static Language _defaultInstance;

  Language_Language get language => $_getN(0);
  set language(Language_Language v) { setField(1, v); }
  $core.bool hasLanguage() => $_has(0);
  void clearLanguage() => clearField(1);

  Language_Script get script => $_getN(1);
  set script(Language_Script v) { setField(2, v); }
  $core.bool hasScript() => $_has(1);
  void clearScript() => clearField(2);

  Location_Country get region => $_getN(2);
  set region(Location_Country v) { setField(3, v); }
  $core.bool hasRegion() => $_has(2);
  void clearRegion() => clearField(3);
}

class Location extends $pb.GeneratedMessage {
  static final $pb.BuilderInfo _i = $pb.BuilderInfo('Location', package: const $pb.PackageName('pb'))
    ..e<Location_Country>(1, 'country', $pb.PbFieldType.OE, Location_Country.UNKNOWN_COUNTRY, Location_Country.valueOf, Location_Country.values)
    ..aOS(2, 'state')
    ..aOS(3, 'city')
    ..aOS(4, 'code')
    ..a<$core.int>(5, 'latitude', $pb.PbFieldType.OS3)
    ..a<$core.int>(6, 'longitude', $pb.PbFieldType.OS3)
    ..hasRequiredFields = false
  ;

  Location._() : super();
  factory Location() => create();
  factory Location.fromBuffer($core.List<$core.int> i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromBuffer(i, r);
  factory Location.fromJson($core.String i, [$pb.ExtensionRegistry r = $pb.ExtensionRegistry.EMPTY]) => create()..mergeFromJson(i, r);
  Location clone() => Location()..mergeFromMessage(this);
  Location copyWith(void Function(Location) updates) => super.copyWith((message) => updates(message as Location));
  $pb.BuilderInfo get info_ => _i;
  @$core.pragma('dart2js:noInline')
  static Location create() => Location._();
  Location createEmptyInstance() => create();
  static $pb.PbList<Location> createRepeated() => $pb.PbList<Location>();
  static Location getDefault() => _defaultInstance ??= create()..freeze();
  static Location _defaultInstance;

  Location_Country get country => $_getN(0);
  set country(Location_Country v) { setField(1, v); }
  $core.bool hasCountry() => $_has(0);
  void clearCountry() => clearField(1);

  $core.String get state => $_getS(1, '');
  set state($core.String v) { $_setString(1, v); }
  $core.bool hasState() => $_has(1);
  void clearState() => clearField(2);

  $core.String get city => $_getS(2, '');
  set city($core.String v) { $_setString(2, v); }
  $core.bool hasCity() => $_has(2);
  void clearCity() => clearField(3);

  $core.String get code => $_getS(3, '');
  set code($core.String v) { $_setString(3, v); }
  $core.bool hasCode() => $_has(3);
  void clearCode() => clearField(4);

  $core.int get latitude => $_get(4, 0);
  set latitude($core.int v) { $_setSignedInt32(4, v); }
  $core.bool hasLatitude() => $_has(4);
  void clearLatitude() => clearField(5);

  $core.int get longitude => $_get(5, 0);
  set longitude($core.int v) { $_setSignedInt32(5, v); }
  $core.bool hasLongitude() => $_has(5);
  void clearLongitude() => clearField(6);
}

