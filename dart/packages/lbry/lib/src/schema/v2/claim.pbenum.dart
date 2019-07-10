///
//  Generated code. Do not modify.
//  source: claim.proto
///
// ignore_for_file: camel_case_types,non_constant_identifier_names,library_prefixes,unused_import,unused_shown_name,return_of_invalid_type

// ignore_for_file: UNDEFINED_SHOWN_NAME,UNUSED_SHOWN_NAME
import 'dart:core' as $core show int, dynamic, String, List, Map;
import 'package:protobuf/protobuf.dart' as $pb;

class ClaimList_ListType extends $pb.ProtobufEnum {
  static const ClaimList_ListType COLLECTION = ClaimList_ListType._(0, 'COLLECTION');
  static const ClaimList_ListType DERIVATION = ClaimList_ListType._(2, 'DERIVATION');

  static const $core.List<ClaimList_ListType> values = <ClaimList_ListType> [
    COLLECTION,
    DERIVATION,
  ];

  static final $core.Map<$core.int, ClaimList_ListType> _byValue = $pb.ProtobufEnum.initByValue(values);
  static ClaimList_ListType valueOf($core.int value) => _byValue[value];

  const ClaimList_ListType._($core.int v, $core.String n) : super(v, n);
}

class Fee_Currency extends $pb.ProtobufEnum {
  static const Fee_Currency UNKNOWN_CURRENCY = Fee_Currency._(0, 'UNKNOWN_CURRENCY');
  static const Fee_Currency LBC = Fee_Currency._(1, 'LBC');
  static const Fee_Currency BTC = Fee_Currency._(2, 'BTC');
  static const Fee_Currency USD = Fee_Currency._(3, 'USD');

  static const $core.List<Fee_Currency> values = <Fee_Currency> [
    UNKNOWN_CURRENCY,
    LBC,
    BTC,
    USD,
  ];

  static final $core.Map<$core.int, Fee_Currency> _byValue = $pb.ProtobufEnum.initByValue(values);
  static Fee_Currency valueOf($core.int value) => _byValue[value];

  const Fee_Currency._($core.int v, $core.String n) : super(v, n);
}

class Software_OS extends $pb.ProtobufEnum {
  static const Software_OS UNKNOWN_OS = Software_OS._(0, 'UNKNOWN_OS');
  static const Software_OS ANY = Software_OS._(1, 'ANY');
  static const Software_OS LINUX = Software_OS._(2, 'LINUX');
  static const Software_OS WINDOWS = Software_OS._(3, 'WINDOWS');
  static const Software_OS MAC = Software_OS._(4, 'MAC');
  static const Software_OS ANDROID = Software_OS._(5, 'ANDROID');
  static const Software_OS IOS = Software_OS._(6, 'IOS');

  static const $core.List<Software_OS> values = <Software_OS> [
    UNKNOWN_OS,
    ANY,
    LINUX,
    WINDOWS,
    MAC,
    ANDROID,
    IOS,
  ];

  static final $core.Map<$core.int, Software_OS> _byValue = $pb.ProtobufEnum.initByValue(values);
  static Software_OS valueOf($core.int value) => _byValue[value];

  const Software_OS._($core.int v, $core.String n) : super(v, n);
}

class Language_Language extends $pb.ProtobufEnum {
  static const Language_Language UNKNOWN_LANGUAGE = Language_Language._(0, 'UNKNOWN_LANGUAGE');
  static const Language_Language en = Language_Language._(1, 'en');
  static const Language_Language aa = Language_Language._(2, 'aa');
  static const Language_Language ab = Language_Language._(3, 'ab');
  static const Language_Language ae = Language_Language._(4, 'ae');
  static const Language_Language af = Language_Language._(5, 'af');
  static const Language_Language ak = Language_Language._(6, 'ak');
  static const Language_Language am = Language_Language._(7, 'am');
  static const Language_Language an = Language_Language._(8, 'an');
  static const Language_Language ar = Language_Language._(9, 'ar');
  static const Language_Language as = Language_Language._(10, 'as');
  static const Language_Language av = Language_Language._(11, 'av');
  static const Language_Language ay = Language_Language._(12, 'ay');
  static const Language_Language az = Language_Language._(13, 'az');
  static const Language_Language ba = Language_Language._(14, 'ba');
  static const Language_Language be = Language_Language._(15, 'be');
  static const Language_Language bg = Language_Language._(16, 'bg');
  static const Language_Language bh = Language_Language._(17, 'bh');
  static const Language_Language bi = Language_Language._(18, 'bi');
  static const Language_Language bm = Language_Language._(19, 'bm');
  static const Language_Language bn = Language_Language._(20, 'bn');
  static const Language_Language bo = Language_Language._(21, 'bo');
  static const Language_Language br = Language_Language._(22, 'br');
  static const Language_Language bs = Language_Language._(23, 'bs');
  static const Language_Language ca = Language_Language._(24, 'ca');
  static const Language_Language ce = Language_Language._(25, 'ce');
  static const Language_Language ch = Language_Language._(26, 'ch');
  static const Language_Language co = Language_Language._(27, 'co');
  static const Language_Language cr = Language_Language._(28, 'cr');
  static const Language_Language cs = Language_Language._(29, 'cs');
  static const Language_Language cu = Language_Language._(30, 'cu');
  static const Language_Language cv = Language_Language._(31, 'cv');
  static const Language_Language cy = Language_Language._(32, 'cy');
  static const Language_Language da = Language_Language._(33, 'da');
  static const Language_Language de = Language_Language._(34, 'de');
  static const Language_Language dv = Language_Language._(35, 'dv');
  static const Language_Language dz = Language_Language._(36, 'dz');
  static const Language_Language ee = Language_Language._(37, 'ee');
  static const Language_Language el = Language_Language._(38, 'el');
  static const Language_Language eo = Language_Language._(39, 'eo');
  static const Language_Language es = Language_Language._(40, 'es');
  static const Language_Language et = Language_Language._(41, 'et');
  static const Language_Language eu = Language_Language._(42, 'eu');
  static const Language_Language fa = Language_Language._(43, 'fa');
  static const Language_Language ff = Language_Language._(44, 'ff');
  static const Language_Language fi = Language_Language._(45, 'fi');
  static const Language_Language fj = Language_Language._(46, 'fj');
  static const Language_Language fo = Language_Language._(47, 'fo');
  static const Language_Language fr = Language_Language._(48, 'fr');
  static const Language_Language fy = Language_Language._(49, 'fy');
  static const Language_Language ga = Language_Language._(50, 'ga');
  static const Language_Language gd = Language_Language._(51, 'gd');
  static const Language_Language gl = Language_Language._(52, 'gl');
  static const Language_Language gn = Language_Language._(53, 'gn');
  static const Language_Language gu = Language_Language._(54, 'gu');
  static const Language_Language gv = Language_Language._(55, 'gv');
  static const Language_Language ha = Language_Language._(56, 'ha');
  static const Language_Language he = Language_Language._(57, 'he');
  static const Language_Language hi = Language_Language._(58, 'hi');
  static const Language_Language ho = Language_Language._(59, 'ho');
  static const Language_Language hr = Language_Language._(60, 'hr');
  static const Language_Language ht = Language_Language._(61, 'ht');
  static const Language_Language hu = Language_Language._(62, 'hu');
  static const Language_Language hy = Language_Language._(63, 'hy');
  static const Language_Language hz = Language_Language._(64, 'hz');
  static const Language_Language ia = Language_Language._(65, 'ia');
  static const Language_Language id = Language_Language._(66, 'id');
  static const Language_Language ie = Language_Language._(67, 'ie');
  static const Language_Language ig = Language_Language._(68, 'ig');
  static const Language_Language ii = Language_Language._(69, 'ii');
  static const Language_Language ik = Language_Language._(70, 'ik');
  static const Language_Language io = Language_Language._(71, 'io');
  static const Language_Language is = Language_Language._(72, 'is');
  static const Language_Language it = Language_Language._(73, 'it');
  static const Language_Language iu = Language_Language._(74, 'iu');
  static const Language_Language ja = Language_Language._(75, 'ja');
  static const Language_Language jv = Language_Language._(76, 'jv');
  static const Language_Language ka = Language_Language._(77, 'ka');
  static const Language_Language kg = Language_Language._(78, 'kg');
  static const Language_Language ki = Language_Language._(79, 'ki');
  static const Language_Language kj = Language_Language._(80, 'kj');
  static const Language_Language kk = Language_Language._(81, 'kk');
  static const Language_Language kl = Language_Language._(82, 'kl');
  static const Language_Language km = Language_Language._(83, 'km');
  static const Language_Language kn = Language_Language._(84, 'kn');
  static const Language_Language ko = Language_Language._(85, 'ko');
  static const Language_Language kr = Language_Language._(86, 'kr');
  static const Language_Language ks = Language_Language._(87, 'ks');
  static const Language_Language ku = Language_Language._(88, 'ku');
  static const Language_Language kv = Language_Language._(89, 'kv');
  static const Language_Language kw = Language_Language._(90, 'kw');
  static const Language_Language ky = Language_Language._(91, 'ky');
  static const Language_Language la = Language_Language._(92, 'la');
  static const Language_Language lb = Language_Language._(93, 'lb');
  static const Language_Language lg = Language_Language._(94, 'lg');
  static const Language_Language li = Language_Language._(95, 'li');
  static const Language_Language ln = Language_Language._(96, 'ln');
  static const Language_Language lo = Language_Language._(97, 'lo');
  static const Language_Language lt = Language_Language._(98, 'lt');
  static const Language_Language lu = Language_Language._(99, 'lu');
  static const Language_Language lv = Language_Language._(100, 'lv');
  static const Language_Language mg = Language_Language._(101, 'mg');
  static const Language_Language mh = Language_Language._(102, 'mh');
  static const Language_Language mi = Language_Language._(103, 'mi');
  static const Language_Language mk = Language_Language._(104, 'mk');
  static const Language_Language ml = Language_Language._(105, 'ml');
  static const Language_Language mn = Language_Language._(106, 'mn');
  static const Language_Language mr = Language_Language._(107, 'mr');
  static const Language_Language ms = Language_Language._(108, 'ms');
  static const Language_Language mt = Language_Language._(109, 'mt');
  static const Language_Language my = Language_Language._(110, 'my');
  static const Language_Language na = Language_Language._(111, 'na');
  static const Language_Language nb = Language_Language._(112, 'nb');
  static const Language_Language nd = Language_Language._(113, 'nd');
  static const Language_Language ne = Language_Language._(114, 'ne');
  static const Language_Language ng = Language_Language._(115, 'ng');
  static const Language_Language nl = Language_Language._(116, 'nl');
  static const Language_Language nn = Language_Language._(117, 'nn');
  static const Language_Language no = Language_Language._(118, 'no');
  static const Language_Language nr = Language_Language._(119, 'nr');
  static const Language_Language nv = Language_Language._(120, 'nv');
  static const Language_Language ny = Language_Language._(121, 'ny');
  static const Language_Language oc = Language_Language._(122, 'oc');
  static const Language_Language oj = Language_Language._(123, 'oj');
  static const Language_Language om = Language_Language._(124, 'om');
  static const Language_Language or = Language_Language._(125, 'or');
  static const Language_Language os = Language_Language._(126, 'os');
  static const Language_Language pa = Language_Language._(127, 'pa');
  static const Language_Language pi = Language_Language._(128, 'pi');
  static const Language_Language pl = Language_Language._(129, 'pl');
  static const Language_Language ps = Language_Language._(130, 'ps');
  static const Language_Language pt = Language_Language._(131, 'pt');
  static const Language_Language qu = Language_Language._(132, 'qu');
  static const Language_Language rm = Language_Language._(133, 'rm');
  static const Language_Language rn = Language_Language._(134, 'rn');
  static const Language_Language ro = Language_Language._(135, 'ro');
  static const Language_Language ru = Language_Language._(136, 'ru');
  static const Language_Language rw = Language_Language._(137, 'rw');
  static const Language_Language sa = Language_Language._(138, 'sa');
  static const Language_Language sc = Language_Language._(139, 'sc');
  static const Language_Language sd = Language_Language._(140, 'sd');
  static const Language_Language se = Language_Language._(141, 'se');
  static const Language_Language sg = Language_Language._(142, 'sg');
  static const Language_Language si = Language_Language._(143, 'si');
  static const Language_Language sk = Language_Language._(144, 'sk');
  static const Language_Language sl = Language_Language._(145, 'sl');
  static const Language_Language sm = Language_Language._(146, 'sm');
  static const Language_Language sn = Language_Language._(147, 'sn');
  static const Language_Language so = Language_Language._(148, 'so');
  static const Language_Language sq = Language_Language._(149, 'sq');
  static const Language_Language sr = Language_Language._(150, 'sr');
  static const Language_Language ss = Language_Language._(151, 'ss');
  static const Language_Language st = Language_Language._(152, 'st');
  static const Language_Language su = Language_Language._(153, 'su');
  static const Language_Language sv = Language_Language._(154, 'sv');
  static const Language_Language sw = Language_Language._(155, 'sw');
  static const Language_Language ta = Language_Language._(156, 'ta');
  static const Language_Language te = Language_Language._(157, 'te');
  static const Language_Language tg = Language_Language._(158, 'tg');
  static const Language_Language th = Language_Language._(159, 'th');
  static const Language_Language ti = Language_Language._(160, 'ti');
  static const Language_Language tk = Language_Language._(161, 'tk');
  static const Language_Language tl = Language_Language._(162, 'tl');
  static const Language_Language tn = Language_Language._(163, 'tn');
  static const Language_Language to = Language_Language._(164, 'to');
  static const Language_Language tr = Language_Language._(165, 'tr');
  static const Language_Language ts = Language_Language._(166, 'ts');
  static const Language_Language tt = Language_Language._(167, 'tt');
  static const Language_Language tw = Language_Language._(168, 'tw');
  static const Language_Language ty = Language_Language._(169, 'ty');
  static const Language_Language ug = Language_Language._(170, 'ug');
  static const Language_Language uk = Language_Language._(171, 'uk');
  static const Language_Language ur = Language_Language._(172, 'ur');
  static const Language_Language uz = Language_Language._(173, 'uz');
  static const Language_Language ve = Language_Language._(174, 've');
  static const Language_Language vi = Language_Language._(175, 'vi');
  static const Language_Language vo = Language_Language._(176, 'vo');
  static const Language_Language wa = Language_Language._(177, 'wa');
  static const Language_Language wo = Language_Language._(178, 'wo');
  static const Language_Language xh = Language_Language._(179, 'xh');
  static const Language_Language yi = Language_Language._(180, 'yi');
  static const Language_Language yo = Language_Language._(181, 'yo');
  static const Language_Language za = Language_Language._(182, 'za');
  static const Language_Language zh = Language_Language._(183, 'zh');
  static const Language_Language zu = Language_Language._(184, 'zu');

  static const $core.List<Language_Language> values = <Language_Language> [
    UNKNOWN_LANGUAGE,
    en,
    aa,
    ab,
    ae,
    af,
    ak,
    am,
    an,
    ar,
    as,
    av,
    ay,
    az,
    ba,
    be,
    bg,
    bh,
    bi,
    bm,
    bn,
    bo,
    br,
    bs,
    ca,
    ce,
    ch,
    co,
    cr,
    cs,
    cu,
    cv,
    cy,
    da,
    de,
    dv,
    dz,
    ee,
    el,
    eo,
    es,
    et,
    eu,
    fa,
    ff,
    fi,
    fj,
    fo,
    fr,
    fy,
    ga,
    gd,
    gl,
    gn,
    gu,
    gv,
    ha,
    he,
    hi,
    ho,
    hr,
    ht,
    hu,
    hy,
    hz,
    ia,
    id,
    ie,
    ig,
    ii,
    ik,
    io,
    is,
    it,
    iu,
    ja,
    jv,
    ka,
    kg,
    ki,
    kj,
    kk,
    kl,
    km,
    kn,
    ko,
    kr,
    ks,
    ku,
    kv,
    kw,
    ky,
    la,
    lb,
    lg,
    li,
    ln,
    lo,
    lt,
    lu,
    lv,
    mg,
    mh,
    mi,
    mk,
    ml,
    mn,
    mr,
    ms,
    mt,
    my,
    na,
    nb,
    nd,
    ne,
    ng,
    nl,
    nn,
    no,
    nr,
    nv,
    ny,
    oc,
    oj,
    om,
    or,
    os,
    pa,
    pi,
    pl,
    ps,
    pt,
    qu,
    rm,
    rn,
    ro,
    ru,
    rw,
    sa,
    sc,
    sd,
    se,
    sg,
    si,
    sk,
    sl,
    sm,
    sn,
    so,
    sq,
    sr,
    ss,
    st,
    su,
    sv,
    sw,
    ta,
    te,
    tg,
    th,
    ti,
    tk,
    tl,
    tn,
    to,
    tr,
    ts,
    tt,
    tw,
    ty,
    ug,
    uk,
    ur,
    uz,
    ve,
    vi,
    vo,
    wa,
    wo,
    xh,
    yi,
    yo,
    za,
    zh,
    zu,
  ];

  static final $core.Map<$core.int, Language_Language> _byValue = $pb.ProtobufEnum.initByValue(values);
  static Language_Language valueOf($core.int value) => _byValue[value];

  const Language_Language._($core.int v, $core.String n) : super(v, n);
}

class Language_Script extends $pb.ProtobufEnum {
  static const Language_Script UNKNOWN_SCRIPT = Language_Script._(0, 'UNKNOWN_SCRIPT');
  static const Language_Script Adlm = Language_Script._(1, 'Adlm');
  static const Language_Script Afak = Language_Script._(2, 'Afak');
  static const Language_Script Aghb = Language_Script._(3, 'Aghb');
  static const Language_Script Ahom = Language_Script._(4, 'Ahom');
  static const Language_Script Arab = Language_Script._(5, 'Arab');
  static const Language_Script Aran = Language_Script._(6, 'Aran');
  static const Language_Script Armi = Language_Script._(7, 'Armi');
  static const Language_Script Armn = Language_Script._(8, 'Armn');
  static const Language_Script Avst = Language_Script._(9, 'Avst');
  static const Language_Script Bali = Language_Script._(10, 'Bali');
  static const Language_Script Bamu = Language_Script._(11, 'Bamu');
  static const Language_Script Bass = Language_Script._(12, 'Bass');
  static const Language_Script Batk = Language_Script._(13, 'Batk');
  static const Language_Script Beng = Language_Script._(14, 'Beng');
  static const Language_Script Bhks = Language_Script._(15, 'Bhks');
  static const Language_Script Blis = Language_Script._(16, 'Blis');
  static const Language_Script Bopo = Language_Script._(17, 'Bopo');
  static const Language_Script Brah = Language_Script._(18, 'Brah');
  static const Language_Script Brai = Language_Script._(19, 'Brai');
  static const Language_Script Bugi = Language_Script._(20, 'Bugi');
  static const Language_Script Buhd = Language_Script._(21, 'Buhd');
  static const Language_Script Cakm = Language_Script._(22, 'Cakm');
  static const Language_Script Cans = Language_Script._(23, 'Cans');
  static const Language_Script Cari = Language_Script._(24, 'Cari');
  static const Language_Script Cham = Language_Script._(25, 'Cham');
  static const Language_Script Cher = Language_Script._(26, 'Cher');
  static const Language_Script Cirt = Language_Script._(27, 'Cirt');
  static const Language_Script Copt = Language_Script._(28, 'Copt');
  static const Language_Script Cpmn = Language_Script._(29, 'Cpmn');
  static const Language_Script Cprt = Language_Script._(30, 'Cprt');
  static const Language_Script Cyrl = Language_Script._(31, 'Cyrl');
  static const Language_Script Cyrs = Language_Script._(32, 'Cyrs');
  static const Language_Script Deva = Language_Script._(33, 'Deva');
  static const Language_Script Dogr = Language_Script._(34, 'Dogr');
  static const Language_Script Dsrt = Language_Script._(35, 'Dsrt');
  static const Language_Script Dupl = Language_Script._(36, 'Dupl');
  static const Language_Script Egyd = Language_Script._(37, 'Egyd');
  static const Language_Script Egyh = Language_Script._(38, 'Egyh');
  static const Language_Script Egyp = Language_Script._(39, 'Egyp');
  static const Language_Script Elba = Language_Script._(40, 'Elba');
  static const Language_Script Elym = Language_Script._(41, 'Elym');
  static const Language_Script Ethi = Language_Script._(42, 'Ethi');
  static const Language_Script Geok = Language_Script._(43, 'Geok');
  static const Language_Script Geor = Language_Script._(44, 'Geor');
  static const Language_Script Glag = Language_Script._(45, 'Glag');
  static const Language_Script Gong = Language_Script._(46, 'Gong');
  static const Language_Script Gonm = Language_Script._(47, 'Gonm');
  static const Language_Script Goth = Language_Script._(48, 'Goth');
  static const Language_Script Gran = Language_Script._(49, 'Gran');
  static const Language_Script Grek = Language_Script._(50, 'Grek');
  static const Language_Script Gujr = Language_Script._(51, 'Gujr');
  static const Language_Script Guru = Language_Script._(52, 'Guru');
  static const Language_Script Hanb = Language_Script._(53, 'Hanb');
  static const Language_Script Hang = Language_Script._(54, 'Hang');
  static const Language_Script Hani = Language_Script._(55, 'Hani');
  static const Language_Script Hano = Language_Script._(56, 'Hano');
  static const Language_Script Hans = Language_Script._(57, 'Hans');
  static const Language_Script Hant = Language_Script._(58, 'Hant');
  static const Language_Script Hatr = Language_Script._(59, 'Hatr');
  static const Language_Script Hebr = Language_Script._(60, 'Hebr');
  static const Language_Script Hira = Language_Script._(61, 'Hira');
  static const Language_Script Hluw = Language_Script._(62, 'Hluw');
  static const Language_Script Hmng = Language_Script._(63, 'Hmng');
  static const Language_Script Hmnp = Language_Script._(64, 'Hmnp');
  static const Language_Script Hrkt = Language_Script._(65, 'Hrkt');
  static const Language_Script Hung = Language_Script._(66, 'Hung');
  static const Language_Script Inds = Language_Script._(67, 'Inds');
  static const Language_Script Ital = Language_Script._(68, 'Ital');
  static const Language_Script Jamo = Language_Script._(69, 'Jamo');
  static const Language_Script Java = Language_Script._(70, 'Java');
  static const Language_Script Jpan = Language_Script._(71, 'Jpan');
  static const Language_Script Jurc = Language_Script._(72, 'Jurc');
  static const Language_Script Kali = Language_Script._(73, 'Kali');
  static const Language_Script Kana = Language_Script._(74, 'Kana');
  static const Language_Script Khar = Language_Script._(75, 'Khar');
  static const Language_Script Khmr = Language_Script._(76, 'Khmr');
  static const Language_Script Khoj = Language_Script._(77, 'Khoj');
  static const Language_Script Kitl = Language_Script._(78, 'Kitl');
  static const Language_Script Kits = Language_Script._(79, 'Kits');
  static const Language_Script Knda = Language_Script._(80, 'Knda');
  static const Language_Script Kore = Language_Script._(81, 'Kore');
  static const Language_Script Kpel = Language_Script._(82, 'Kpel');
  static const Language_Script Kthi = Language_Script._(83, 'Kthi');
  static const Language_Script Lana = Language_Script._(84, 'Lana');
  static const Language_Script Laoo = Language_Script._(85, 'Laoo');
  static const Language_Script Latf = Language_Script._(86, 'Latf');
  static const Language_Script Latg = Language_Script._(87, 'Latg');
  static const Language_Script Latn = Language_Script._(88, 'Latn');
  static const Language_Script Leke = Language_Script._(89, 'Leke');
  static const Language_Script Lepc = Language_Script._(90, 'Lepc');
  static const Language_Script Limb = Language_Script._(91, 'Limb');
  static const Language_Script Lina = Language_Script._(92, 'Lina');
  static const Language_Script Linb = Language_Script._(93, 'Linb');
  static const Language_Script Lisu = Language_Script._(94, 'Lisu');
  static const Language_Script Loma = Language_Script._(95, 'Loma');
  static const Language_Script Lyci = Language_Script._(96, 'Lyci');
  static const Language_Script Lydi = Language_Script._(97, 'Lydi');
  static const Language_Script Mahj = Language_Script._(98, 'Mahj');
  static const Language_Script Maka = Language_Script._(99, 'Maka');
  static const Language_Script Mand = Language_Script._(100, 'Mand');
  static const Language_Script Mani = Language_Script._(101, 'Mani');
  static const Language_Script Marc = Language_Script._(102, 'Marc');
  static const Language_Script Maya = Language_Script._(103, 'Maya');
  static const Language_Script Medf = Language_Script._(104, 'Medf');
  static const Language_Script Mend = Language_Script._(105, 'Mend');
  static const Language_Script Merc = Language_Script._(106, 'Merc');
  static const Language_Script Mero = Language_Script._(107, 'Mero');
  static const Language_Script Mlym = Language_Script._(108, 'Mlym');
  static const Language_Script Modi = Language_Script._(109, 'Modi');
  static const Language_Script Mong = Language_Script._(110, 'Mong');
  static const Language_Script Moon = Language_Script._(111, 'Moon');
  static const Language_Script Mroo = Language_Script._(112, 'Mroo');
  static const Language_Script Mtei = Language_Script._(113, 'Mtei');
  static const Language_Script Mult = Language_Script._(114, 'Mult');
  static const Language_Script Mymr = Language_Script._(115, 'Mymr');
  static const Language_Script Nand = Language_Script._(116, 'Nand');
  static const Language_Script Narb = Language_Script._(117, 'Narb');
  static const Language_Script Nbat = Language_Script._(118, 'Nbat');
  static const Language_Script Newa = Language_Script._(119, 'Newa');
  static const Language_Script Nkdb = Language_Script._(120, 'Nkdb');
  static const Language_Script Nkgb = Language_Script._(121, 'Nkgb');
  static const Language_Script Nkoo = Language_Script._(122, 'Nkoo');
  static const Language_Script Nshu = Language_Script._(123, 'Nshu');
  static const Language_Script Ogam = Language_Script._(124, 'Ogam');
  static const Language_Script Olck = Language_Script._(125, 'Olck');
  static const Language_Script Orkh = Language_Script._(126, 'Orkh');
  static const Language_Script Orya = Language_Script._(127, 'Orya');
  static const Language_Script Osge = Language_Script._(128, 'Osge');
  static const Language_Script Osma = Language_Script._(129, 'Osma');
  static const Language_Script Palm = Language_Script._(130, 'Palm');
  static const Language_Script Pauc = Language_Script._(131, 'Pauc');
  static const Language_Script Perm = Language_Script._(132, 'Perm');
  static const Language_Script Phag = Language_Script._(133, 'Phag');
  static const Language_Script Phli = Language_Script._(134, 'Phli');
  static const Language_Script Phlp = Language_Script._(135, 'Phlp');
  static const Language_Script Phlv = Language_Script._(136, 'Phlv');
  static const Language_Script Phnx = Language_Script._(137, 'Phnx');
  static const Language_Script Plrd = Language_Script._(138, 'Plrd');
  static const Language_Script Piqd = Language_Script._(139, 'Piqd');
  static const Language_Script Prti = Language_Script._(140, 'Prti');
  static const Language_Script Qaaa = Language_Script._(141, 'Qaaa');
  static const Language_Script Qabx = Language_Script._(142, 'Qabx');
  static const Language_Script Rjng = Language_Script._(143, 'Rjng');
  static const Language_Script Rohg = Language_Script._(144, 'Rohg');
  static const Language_Script Roro = Language_Script._(145, 'Roro');
  static const Language_Script Runr = Language_Script._(146, 'Runr');
  static const Language_Script Samr = Language_Script._(147, 'Samr');
  static const Language_Script Sara = Language_Script._(148, 'Sara');
  static const Language_Script Sarb = Language_Script._(149, 'Sarb');
  static const Language_Script Saur = Language_Script._(150, 'Saur');
  static const Language_Script Sgnw = Language_Script._(151, 'Sgnw');
  static const Language_Script Shaw = Language_Script._(152, 'Shaw');
  static const Language_Script Shrd = Language_Script._(153, 'Shrd');
  static const Language_Script Shui = Language_Script._(154, 'Shui');
  static const Language_Script Sidd = Language_Script._(155, 'Sidd');
  static const Language_Script Sind = Language_Script._(156, 'Sind');
  static const Language_Script Sinh = Language_Script._(157, 'Sinh');
  static const Language_Script Sogd = Language_Script._(158, 'Sogd');
  static const Language_Script Sogo = Language_Script._(159, 'Sogo');
  static const Language_Script Sora = Language_Script._(160, 'Sora');
  static const Language_Script Soyo = Language_Script._(161, 'Soyo');
  static const Language_Script Sund = Language_Script._(162, 'Sund');
  static const Language_Script Sylo = Language_Script._(163, 'Sylo');
  static const Language_Script Syrc = Language_Script._(164, 'Syrc');
  static const Language_Script Syre = Language_Script._(165, 'Syre');
  static const Language_Script Syrj = Language_Script._(166, 'Syrj');
  static const Language_Script Syrn = Language_Script._(167, 'Syrn');
  static const Language_Script Tagb = Language_Script._(168, 'Tagb');
  static const Language_Script Takr = Language_Script._(169, 'Takr');
  static const Language_Script Tale = Language_Script._(170, 'Tale');
  static const Language_Script Talu = Language_Script._(171, 'Talu');
  static const Language_Script Taml = Language_Script._(172, 'Taml');
  static const Language_Script Tang = Language_Script._(173, 'Tang');
  static const Language_Script Tavt = Language_Script._(174, 'Tavt');
  static const Language_Script Telu = Language_Script._(175, 'Telu');
  static const Language_Script Teng = Language_Script._(176, 'Teng');
  static const Language_Script Tfng = Language_Script._(177, 'Tfng');
  static const Language_Script Tglg = Language_Script._(178, 'Tglg');
  static const Language_Script Thaa = Language_Script._(179, 'Thaa');
  static const Language_Script Thai = Language_Script._(180, 'Thai');
  static const Language_Script Tibt = Language_Script._(181, 'Tibt');
  static const Language_Script Tirh = Language_Script._(182, 'Tirh');
  static const Language_Script Ugar = Language_Script._(183, 'Ugar');
  static const Language_Script Vaii = Language_Script._(184, 'Vaii');
  static const Language_Script Visp = Language_Script._(185, 'Visp');
  static const Language_Script Wara = Language_Script._(186, 'Wara');
  static const Language_Script Wcho = Language_Script._(187, 'Wcho');
  static const Language_Script Wole = Language_Script._(188, 'Wole');
  static const Language_Script Xpeo = Language_Script._(189, 'Xpeo');
  static const Language_Script Xsux = Language_Script._(190, 'Xsux');
  static const Language_Script Yiii = Language_Script._(191, 'Yiii');
  static const Language_Script Zanb = Language_Script._(192, 'Zanb');
  static const Language_Script Zinh = Language_Script._(193, 'Zinh');
  static const Language_Script Zmth = Language_Script._(194, 'Zmth');
  static const Language_Script Zsye = Language_Script._(195, 'Zsye');
  static const Language_Script Zsym = Language_Script._(196, 'Zsym');
  static const Language_Script Zxxx = Language_Script._(197, 'Zxxx');
  static const Language_Script Zyyy = Language_Script._(198, 'Zyyy');
  static const Language_Script Zzzz = Language_Script._(199, 'Zzzz');

  static const $core.List<Language_Script> values = <Language_Script> [
    UNKNOWN_SCRIPT,
    Adlm,
    Afak,
    Aghb,
    Ahom,
    Arab,
    Aran,
    Armi,
    Armn,
    Avst,
    Bali,
    Bamu,
    Bass,
    Batk,
    Beng,
    Bhks,
    Blis,
    Bopo,
    Brah,
    Brai,
    Bugi,
    Buhd,
    Cakm,
    Cans,
    Cari,
    Cham,
    Cher,
    Cirt,
    Copt,
    Cpmn,
    Cprt,
    Cyrl,
    Cyrs,
    Deva,
    Dogr,
    Dsrt,
    Dupl,
    Egyd,
    Egyh,
    Egyp,
    Elba,
    Elym,
    Ethi,
    Geok,
    Geor,
    Glag,
    Gong,
    Gonm,
    Goth,
    Gran,
    Grek,
    Gujr,
    Guru,
    Hanb,
    Hang,
    Hani,
    Hano,
    Hans,
    Hant,
    Hatr,
    Hebr,
    Hira,
    Hluw,
    Hmng,
    Hmnp,
    Hrkt,
    Hung,
    Inds,
    Ital,
    Jamo,
    Java,
    Jpan,
    Jurc,
    Kali,
    Kana,
    Khar,
    Khmr,
    Khoj,
    Kitl,
    Kits,
    Knda,
    Kore,
    Kpel,
    Kthi,
    Lana,
    Laoo,
    Latf,
    Latg,
    Latn,
    Leke,
    Lepc,
    Limb,
    Lina,
    Linb,
    Lisu,
    Loma,
    Lyci,
    Lydi,
    Mahj,
    Maka,
    Mand,
    Mani,
    Marc,
    Maya,
    Medf,
    Mend,
    Merc,
    Mero,
    Mlym,
    Modi,
    Mong,
    Moon,
    Mroo,
    Mtei,
    Mult,
    Mymr,
    Nand,
    Narb,
    Nbat,
    Newa,
    Nkdb,
    Nkgb,
    Nkoo,
    Nshu,
    Ogam,
    Olck,
    Orkh,
    Orya,
    Osge,
    Osma,
    Palm,
    Pauc,
    Perm,
    Phag,
    Phli,
    Phlp,
    Phlv,
    Phnx,
    Plrd,
    Piqd,
    Prti,
    Qaaa,
    Qabx,
    Rjng,
    Rohg,
    Roro,
    Runr,
    Samr,
    Sara,
    Sarb,
    Saur,
    Sgnw,
    Shaw,
    Shrd,
    Shui,
    Sidd,
    Sind,
    Sinh,
    Sogd,
    Sogo,
    Sora,
    Soyo,
    Sund,
    Sylo,
    Syrc,
    Syre,
    Syrj,
    Syrn,
    Tagb,
    Takr,
    Tale,
    Talu,
    Taml,
    Tang,
    Tavt,
    Telu,
    Teng,
    Tfng,
    Tglg,
    Thaa,
    Thai,
    Tibt,
    Tirh,
    Ugar,
    Vaii,
    Visp,
    Wara,
    Wcho,
    Wole,
    Xpeo,
    Xsux,
    Yiii,
    Zanb,
    Zinh,
    Zmth,
    Zsye,
    Zsym,
    Zxxx,
    Zyyy,
    Zzzz,
  ];

  static final $core.Map<$core.int, Language_Script> _byValue = $pb.ProtobufEnum.initByValue(values);
  static Language_Script valueOf($core.int value) => _byValue[value];

  const Language_Script._($core.int v, $core.String n) : super(v, n);
}

class Location_Country extends $pb.ProtobufEnum {
  static const Location_Country UNKNOWN_COUNTRY = Location_Country._(0, 'UNKNOWN_COUNTRY');
  static const Location_Country AF = Location_Country._(1, 'AF');
  static const Location_Country AX = Location_Country._(2, 'AX');
  static const Location_Country AL = Location_Country._(3, 'AL');
  static const Location_Country DZ = Location_Country._(4, 'DZ');
  static const Location_Country AS = Location_Country._(5, 'AS');
  static const Location_Country AD = Location_Country._(6, 'AD');
  static const Location_Country AO = Location_Country._(7, 'AO');
  static const Location_Country AI = Location_Country._(8, 'AI');
  static const Location_Country AQ = Location_Country._(9, 'AQ');
  static const Location_Country AG = Location_Country._(10, 'AG');
  static const Location_Country AR = Location_Country._(11, 'AR');
  static const Location_Country AM = Location_Country._(12, 'AM');
  static const Location_Country AW = Location_Country._(13, 'AW');
  static const Location_Country AU = Location_Country._(14, 'AU');
  static const Location_Country AT = Location_Country._(15, 'AT');
  static const Location_Country AZ = Location_Country._(16, 'AZ');
  static const Location_Country BS = Location_Country._(17, 'BS');
  static const Location_Country BH = Location_Country._(18, 'BH');
  static const Location_Country BD = Location_Country._(19, 'BD');
  static const Location_Country BB = Location_Country._(20, 'BB');
  static const Location_Country BY = Location_Country._(21, 'BY');
  static const Location_Country BE = Location_Country._(22, 'BE');
  static const Location_Country BZ = Location_Country._(23, 'BZ');
  static const Location_Country BJ = Location_Country._(24, 'BJ');
  static const Location_Country BM = Location_Country._(25, 'BM');
  static const Location_Country BT = Location_Country._(26, 'BT');
  static const Location_Country BO = Location_Country._(27, 'BO');
  static const Location_Country BQ = Location_Country._(28, 'BQ');
  static const Location_Country BA = Location_Country._(29, 'BA');
  static const Location_Country BW = Location_Country._(30, 'BW');
  static const Location_Country BV = Location_Country._(31, 'BV');
  static const Location_Country BR = Location_Country._(32, 'BR');
  static const Location_Country IO = Location_Country._(33, 'IO');
  static const Location_Country BN = Location_Country._(34, 'BN');
  static const Location_Country BG = Location_Country._(35, 'BG');
  static const Location_Country BF = Location_Country._(36, 'BF');
  static const Location_Country BI = Location_Country._(37, 'BI');
  static const Location_Country KH = Location_Country._(38, 'KH');
  static const Location_Country CM = Location_Country._(39, 'CM');
  static const Location_Country CA = Location_Country._(40, 'CA');
  static const Location_Country CV = Location_Country._(41, 'CV');
  static const Location_Country KY = Location_Country._(42, 'KY');
  static const Location_Country CF = Location_Country._(43, 'CF');
  static const Location_Country TD = Location_Country._(44, 'TD');
  static const Location_Country CL = Location_Country._(45, 'CL');
  static const Location_Country CN = Location_Country._(46, 'CN');
  static const Location_Country CX = Location_Country._(47, 'CX');
  static const Location_Country CC = Location_Country._(48, 'CC');
  static const Location_Country CO = Location_Country._(49, 'CO');
  static const Location_Country KM = Location_Country._(50, 'KM');
  static const Location_Country CG = Location_Country._(51, 'CG');
  static const Location_Country CD = Location_Country._(52, 'CD');
  static const Location_Country CK = Location_Country._(53, 'CK');
  static const Location_Country CR = Location_Country._(54, 'CR');
  static const Location_Country CI = Location_Country._(55, 'CI');
  static const Location_Country HR = Location_Country._(56, 'HR');
  static const Location_Country CU = Location_Country._(57, 'CU');
  static const Location_Country CW = Location_Country._(58, 'CW');
  static const Location_Country CY = Location_Country._(59, 'CY');
  static const Location_Country CZ = Location_Country._(60, 'CZ');
  static const Location_Country DK = Location_Country._(61, 'DK');
  static const Location_Country DJ = Location_Country._(62, 'DJ');
  static const Location_Country DM = Location_Country._(63, 'DM');
  static const Location_Country DO = Location_Country._(64, 'DO');
  static const Location_Country EC = Location_Country._(65, 'EC');
  static const Location_Country EG = Location_Country._(66, 'EG');
  static const Location_Country SV = Location_Country._(67, 'SV');
  static const Location_Country GQ = Location_Country._(68, 'GQ');
  static const Location_Country ER = Location_Country._(69, 'ER');
  static const Location_Country EE = Location_Country._(70, 'EE');
  static const Location_Country ET = Location_Country._(71, 'ET');
  static const Location_Country FK = Location_Country._(72, 'FK');
  static const Location_Country FO = Location_Country._(73, 'FO');
  static const Location_Country FJ = Location_Country._(74, 'FJ');
  static const Location_Country FI = Location_Country._(75, 'FI');
  static const Location_Country FR = Location_Country._(76, 'FR');
  static const Location_Country GF = Location_Country._(77, 'GF');
  static const Location_Country PF = Location_Country._(78, 'PF');
  static const Location_Country TF = Location_Country._(79, 'TF');
  static const Location_Country GA = Location_Country._(80, 'GA');
  static const Location_Country GM = Location_Country._(81, 'GM');
  static const Location_Country GE = Location_Country._(82, 'GE');
  static const Location_Country DE = Location_Country._(83, 'DE');
  static const Location_Country GH = Location_Country._(84, 'GH');
  static const Location_Country GI = Location_Country._(85, 'GI');
  static const Location_Country GR = Location_Country._(86, 'GR');
  static const Location_Country GL = Location_Country._(87, 'GL');
  static const Location_Country GD = Location_Country._(88, 'GD');
  static const Location_Country GP = Location_Country._(89, 'GP');
  static const Location_Country GU = Location_Country._(90, 'GU');
  static const Location_Country GT = Location_Country._(91, 'GT');
  static const Location_Country GG = Location_Country._(92, 'GG');
  static const Location_Country GN = Location_Country._(93, 'GN');
  static const Location_Country GW = Location_Country._(94, 'GW');
  static const Location_Country GY = Location_Country._(95, 'GY');
  static const Location_Country HT = Location_Country._(96, 'HT');
  static const Location_Country HM = Location_Country._(97, 'HM');
  static const Location_Country VA = Location_Country._(98, 'VA');
  static const Location_Country HN = Location_Country._(99, 'HN');
  static const Location_Country HK = Location_Country._(100, 'HK');
  static const Location_Country HU = Location_Country._(101, 'HU');
  static const Location_Country IS = Location_Country._(102, 'IS');
  static const Location_Country IN = Location_Country._(103, 'IN');
  static const Location_Country ID = Location_Country._(104, 'ID');
  static const Location_Country IR = Location_Country._(105, 'IR');
  static const Location_Country IQ = Location_Country._(106, 'IQ');
  static const Location_Country IE = Location_Country._(107, 'IE');
  static const Location_Country IM = Location_Country._(108, 'IM');
  static const Location_Country IL = Location_Country._(109, 'IL');
  static const Location_Country IT = Location_Country._(110, 'IT');
  static const Location_Country JM = Location_Country._(111, 'JM');
  static const Location_Country JP = Location_Country._(112, 'JP');
  static const Location_Country JE = Location_Country._(113, 'JE');
  static const Location_Country JO = Location_Country._(114, 'JO');
  static const Location_Country KZ = Location_Country._(115, 'KZ');
  static const Location_Country KE = Location_Country._(116, 'KE');
  static const Location_Country KI = Location_Country._(117, 'KI');
  static const Location_Country KP = Location_Country._(118, 'KP');
  static const Location_Country KR = Location_Country._(119, 'KR');
  static const Location_Country KW = Location_Country._(120, 'KW');
  static const Location_Country KG = Location_Country._(121, 'KG');
  static const Location_Country LA = Location_Country._(122, 'LA');
  static const Location_Country LV = Location_Country._(123, 'LV');
  static const Location_Country LB = Location_Country._(124, 'LB');
  static const Location_Country LS = Location_Country._(125, 'LS');
  static const Location_Country LR = Location_Country._(126, 'LR');
  static const Location_Country LY = Location_Country._(127, 'LY');
  static const Location_Country LI = Location_Country._(128, 'LI');
  static const Location_Country LT = Location_Country._(129, 'LT');
  static const Location_Country LU = Location_Country._(130, 'LU');
  static const Location_Country MO = Location_Country._(131, 'MO');
  static const Location_Country MK = Location_Country._(132, 'MK');
  static const Location_Country MG = Location_Country._(133, 'MG');
  static const Location_Country MW = Location_Country._(134, 'MW');
  static const Location_Country MY = Location_Country._(135, 'MY');
  static const Location_Country MV = Location_Country._(136, 'MV');
  static const Location_Country ML = Location_Country._(137, 'ML');
  static const Location_Country MT = Location_Country._(138, 'MT');
  static const Location_Country MH = Location_Country._(139, 'MH');
  static const Location_Country MQ = Location_Country._(140, 'MQ');
  static const Location_Country MR = Location_Country._(141, 'MR');
  static const Location_Country MU = Location_Country._(142, 'MU');
  static const Location_Country YT = Location_Country._(143, 'YT');
  static const Location_Country MX = Location_Country._(144, 'MX');
  static const Location_Country FM = Location_Country._(145, 'FM');
  static const Location_Country MD = Location_Country._(146, 'MD');
  static const Location_Country MC = Location_Country._(147, 'MC');
  static const Location_Country MN = Location_Country._(148, 'MN');
  static const Location_Country ME = Location_Country._(149, 'ME');
  static const Location_Country MS = Location_Country._(150, 'MS');
  static const Location_Country MA = Location_Country._(151, 'MA');
  static const Location_Country MZ = Location_Country._(152, 'MZ');
  static const Location_Country MM = Location_Country._(153, 'MM');
  static const Location_Country NA = Location_Country._(154, 'NA');
  static const Location_Country NR = Location_Country._(155, 'NR');
  static const Location_Country NP = Location_Country._(156, 'NP');
  static const Location_Country NL = Location_Country._(157, 'NL');
  static const Location_Country NC = Location_Country._(158, 'NC');
  static const Location_Country NZ = Location_Country._(159, 'NZ');
  static const Location_Country NI = Location_Country._(160, 'NI');
  static const Location_Country NE = Location_Country._(161, 'NE');
  static const Location_Country NG = Location_Country._(162, 'NG');
  static const Location_Country NU = Location_Country._(163, 'NU');
  static const Location_Country NF = Location_Country._(164, 'NF');
  static const Location_Country MP = Location_Country._(165, 'MP');
  static const Location_Country NO = Location_Country._(166, 'NO');
  static const Location_Country OM = Location_Country._(167, 'OM');
  static const Location_Country PK = Location_Country._(168, 'PK');
  static const Location_Country PW = Location_Country._(169, 'PW');
  static const Location_Country PS = Location_Country._(170, 'PS');
  static const Location_Country PA = Location_Country._(171, 'PA');
  static const Location_Country PG = Location_Country._(172, 'PG');
  static const Location_Country PY = Location_Country._(173, 'PY');
  static const Location_Country PE = Location_Country._(174, 'PE');
  static const Location_Country PH = Location_Country._(175, 'PH');
  static const Location_Country PN = Location_Country._(176, 'PN');
  static const Location_Country PL = Location_Country._(177, 'PL');
  static const Location_Country PT = Location_Country._(178, 'PT');
  static const Location_Country PR = Location_Country._(179, 'PR');
  static const Location_Country QA = Location_Country._(180, 'QA');
  static const Location_Country RE = Location_Country._(181, 'RE');
  static const Location_Country RO = Location_Country._(182, 'RO');
  static const Location_Country RU = Location_Country._(183, 'RU');
  static const Location_Country RW = Location_Country._(184, 'RW');
  static const Location_Country BL = Location_Country._(185, 'BL');
  static const Location_Country SH = Location_Country._(186, 'SH');
  static const Location_Country KN = Location_Country._(187, 'KN');
  static const Location_Country LC = Location_Country._(188, 'LC');
  static const Location_Country MF = Location_Country._(189, 'MF');
  static const Location_Country PM = Location_Country._(190, 'PM');
  static const Location_Country VC = Location_Country._(191, 'VC');
  static const Location_Country WS = Location_Country._(192, 'WS');
  static const Location_Country SM = Location_Country._(193, 'SM');
  static const Location_Country ST = Location_Country._(194, 'ST');
  static const Location_Country SA = Location_Country._(195, 'SA');
  static const Location_Country SN = Location_Country._(196, 'SN');
  static const Location_Country RS = Location_Country._(197, 'RS');
  static const Location_Country SC = Location_Country._(198, 'SC');
  static const Location_Country SL = Location_Country._(199, 'SL');
  static const Location_Country SG = Location_Country._(200, 'SG');
  static const Location_Country SX = Location_Country._(201, 'SX');
  static const Location_Country SK = Location_Country._(202, 'SK');
  static const Location_Country SI = Location_Country._(203, 'SI');
  static const Location_Country SB = Location_Country._(204, 'SB');
  static const Location_Country SO = Location_Country._(205, 'SO');
  static const Location_Country ZA = Location_Country._(206, 'ZA');
  static const Location_Country GS = Location_Country._(207, 'GS');
  static const Location_Country SS = Location_Country._(208, 'SS');
  static const Location_Country ES = Location_Country._(209, 'ES');
  static const Location_Country LK = Location_Country._(210, 'LK');
  static const Location_Country SD = Location_Country._(211, 'SD');
  static const Location_Country SR = Location_Country._(212, 'SR');
  static const Location_Country SJ = Location_Country._(213, 'SJ');
  static const Location_Country SZ = Location_Country._(214, 'SZ');
  static const Location_Country SE = Location_Country._(215, 'SE');
  static const Location_Country CH = Location_Country._(216, 'CH');
  static const Location_Country SY = Location_Country._(217, 'SY');
  static const Location_Country TW = Location_Country._(218, 'TW');
  static const Location_Country TJ = Location_Country._(219, 'TJ');
  static const Location_Country TZ = Location_Country._(220, 'TZ');
  static const Location_Country TH = Location_Country._(221, 'TH');
  static const Location_Country TL = Location_Country._(222, 'TL');
  static const Location_Country TG = Location_Country._(223, 'TG');
  static const Location_Country TK = Location_Country._(224, 'TK');
  static const Location_Country TO = Location_Country._(225, 'TO');
  static const Location_Country TT = Location_Country._(226, 'TT');
  static const Location_Country TN = Location_Country._(227, 'TN');
  static const Location_Country TR = Location_Country._(228, 'TR');
  static const Location_Country TM = Location_Country._(229, 'TM');
  static const Location_Country TC = Location_Country._(230, 'TC');
  static const Location_Country TV = Location_Country._(231, 'TV');
  static const Location_Country UG = Location_Country._(232, 'UG');
  static const Location_Country UA = Location_Country._(233, 'UA');
  static const Location_Country AE = Location_Country._(234, 'AE');
  static const Location_Country GB = Location_Country._(235, 'GB');
  static const Location_Country US = Location_Country._(236, 'US');
  static const Location_Country UM = Location_Country._(237, 'UM');
  static const Location_Country UY = Location_Country._(238, 'UY');
  static const Location_Country UZ = Location_Country._(239, 'UZ');
  static const Location_Country VU = Location_Country._(240, 'VU');
  static const Location_Country VE = Location_Country._(241, 'VE');
  static const Location_Country VN = Location_Country._(242, 'VN');
  static const Location_Country VG = Location_Country._(243, 'VG');
  static const Location_Country VI = Location_Country._(244, 'VI');
  static const Location_Country WF = Location_Country._(245, 'WF');
  static const Location_Country EH = Location_Country._(246, 'EH');
  static const Location_Country YE = Location_Country._(247, 'YE');
  static const Location_Country ZM = Location_Country._(248, 'ZM');
  static const Location_Country ZW = Location_Country._(249, 'ZW');

  static const $core.List<Location_Country> values = <Location_Country> [
    UNKNOWN_COUNTRY,
    AF,
    AX,
    AL,
    DZ,
    AS,
    AD,
    AO,
    AI,
    AQ,
    AG,
    AR,
    AM,
    AW,
    AU,
    AT,
    AZ,
    BS,
    BH,
    BD,
    BB,
    BY,
    BE,
    BZ,
    BJ,
    BM,
    BT,
    BO,
    BQ,
    BA,
    BW,
    BV,
    BR,
    IO,
    BN,
    BG,
    BF,
    BI,
    KH,
    CM,
    CA,
    CV,
    KY,
    CF,
    TD,
    CL,
    CN,
    CX,
    CC,
    CO,
    KM,
    CG,
    CD,
    CK,
    CR,
    CI,
    HR,
    CU,
    CW,
    CY,
    CZ,
    DK,
    DJ,
    DM,
    DO,
    EC,
    EG,
    SV,
    GQ,
    ER,
    EE,
    ET,
    FK,
    FO,
    FJ,
    FI,
    FR,
    GF,
    PF,
    TF,
    GA,
    GM,
    GE,
    DE,
    GH,
    GI,
    GR,
    GL,
    GD,
    GP,
    GU,
    GT,
    GG,
    GN,
    GW,
    GY,
    HT,
    HM,
    VA,
    HN,
    HK,
    HU,
    IS,
    IN,
    ID,
    IR,
    IQ,
    IE,
    IM,
    IL,
    IT,
    JM,
    JP,
    JE,
    JO,
    KZ,
    KE,
    KI,
    KP,
    KR,
    KW,
    KG,
    LA,
    LV,
    LB,
    LS,
    LR,
    LY,
    LI,
    LT,
    LU,
    MO,
    MK,
    MG,
    MW,
    MY,
    MV,
    ML,
    MT,
    MH,
    MQ,
    MR,
    MU,
    YT,
    MX,
    FM,
    MD,
    MC,
    MN,
    ME,
    MS,
    MA,
    MZ,
    MM,
    NA,
    NR,
    NP,
    NL,
    NC,
    NZ,
    NI,
    NE,
    NG,
    NU,
    NF,
    MP,
    NO,
    OM,
    PK,
    PW,
    PS,
    PA,
    PG,
    PY,
    PE,
    PH,
    PN,
    PL,
    PT,
    PR,
    QA,
    RE,
    RO,
    RU,
    RW,
    BL,
    SH,
    KN,
    LC,
    MF,
    PM,
    VC,
    WS,
    SM,
    ST,
    SA,
    SN,
    RS,
    SC,
    SL,
    SG,
    SX,
    SK,
    SI,
    SB,
    SO,
    ZA,
    GS,
    SS,
    ES,
    LK,
    SD,
    SR,
    SJ,
    SZ,
    SE,
    CH,
    SY,
    TW,
    TJ,
    TZ,
    TH,
    TL,
    TG,
    TK,
    TO,
    TT,
    TN,
    TR,
    TM,
    TC,
    TV,
    UG,
    UA,
    AE,
    GB,
    US,
    UM,
    UY,
    UZ,
    VU,
    VE,
    VN,
    VG,
    VI,
    WF,
    EH,
    YE,
    ZM,
    ZW,
  ];

  static final $core.Map<$core.int, Location_Country> _byValue = $pb.ProtobufEnum.initByValue(values);
  static Location_Country valueOf($core.int value) => _byValue[value];

  const Location_Country._($core.int v, $core.String n) : super(v, n);
}

