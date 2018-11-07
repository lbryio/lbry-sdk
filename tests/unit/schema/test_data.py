

claim_id_1 = "63f2da17b0d90042c559cc73b6b17f853945c43e"

claim_address_2 = "bDtL6qriyimxz71DSYjojTBsm6cpM1bqmj"

claim_address_1 = "bUG7VaMzLEqqyZQAyg9srxQzvf1wwnJ48w"

nist256p_private_key = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIBhixPFinjHmG94r00VBjmE73XZmlSHag5Bg3BFdCeQgoAoGCCqGSM49
AwEHoUQDQgAEtSfatRTR6ppwoDVJ94hbvhFDF42mACkWSc2Tao6zzYW4xaRPbI7j
IBUL+6prbDM+GXZ8X2mtmeaNIgjWTT7YFw==
-----END EC PRIVATE KEY-----
"""

nist384p_private_key = """-----BEGIN EC PRIVATE KEY-----
MIGkAgEBBDD5PPbcgT62WADeVBkDFsKCTCwQULHD7eE0iZz7c9Xk+6gZazMFgsGp
O0Rs9n+lmACgBwYFK4EEACKhZANiAASzpp0t4nIxoedhQN+J2pZ/EmwZl/x4dwdd
AjY4ZwKBdhfWIWgtcET9PBJlda0EvxR+CTwrt1em26VNS/57eH3yNFJQdCQiMSFY
mTtML6D/rctN1oztTSQdwHPA9x99FcU=
-----END EC PRIVATE KEY-----
"""

secp256k1_private_key = """-----BEGIN EC PRIVATE KEY-----
MHQCAQEEIPbjaEfCCCy5HHvGHkEw3X/dTJXlr4jcEJHV1OmcBDPmoAcGBSuBBAAK
oUQDQgAElLPrkVIapvtKrv0DkgQb9vAXtCQDBIu+iHlsQC5dx1ZnOWZwpYKQuM4i
LNbuTlfxCHWYwovwLjYnao8iwgp0og==
-----END EC PRIVATE KEY-----
"""

nist256p_cert = {
  "version": "_0_0_1", 
  "claimType": "certificateType", 
  "certificate": {
    "publicKey": "3059301306072a8648ce3d020106082a8648ce3d03010703420004b527dab514d1ea9a70a03549f7885bbe1143178da600291649cd936a8eb3cd85b8c5a44f6c8ee320150bfbaa6b6c333e19767c5f69ad99e68d2208d64d3ed817", 
    "keyType": "NIST256p", 
    "version": "_0_0_1"
  }
}

nist384p_cert = {
  "version": "_0_0_1", 
  "claimType": "certificateType", 
  "certificate": {
    "publicKey": "3076301006072a8648ce3d020106052b8104002203620004b3a69d2de27231a1e76140df89da967f126c1997fc7877075d0236386702817617d621682d7044fd3c126575ad04bf147e093c2bb757a6dba54d4bfe7b787df2345250742422312158993b4c2fa0ffadcb4dd68ced4d241dc073c0f71f7d15c5", 
    "keyType": "NIST384p", 
    "version": "_0_0_1"
  }
}

secp256k1_cert = {
  "version": "_0_0_1", 
  "claimType": "certificateType", 
  "certificate": {
    "publicKey": "3056301006072a8648ce3d020106052b8104000a0342000494b3eb91521aa6fb4aaefd0392041bf6f017b42403048bbe88796c402e5dc75667396670a58290b8ce222cd6ee4e57f1087598c28bf02e36276a8f22c20a74a2", 
    "keyType": "SECP256k1", 
    "version": "_0_0_1"
  }
}

malformed_secp256k1_cert = {
  "version": "_0_0_1",
  "claimType": "certificateType",
  "certificate": {
    "publicKey": "3056301006072a8648ce3d020106052b8104000a0342000494b3eb91521aa6fb4aaefd0392041bf6f017b42403048bbe88796c402e5dc75667396670a58290b8ce222cd6ee4e57f1087598c28bf02e36276a8f22c20a74a2",
    "keyType": "NIST256p",
    "version": "_0_0_1"
  }
}

example_003 = {
  "language": "en", 
  "license": "LBRY Inc", 
  "nsfw": False, 
  "description": "What is LBRY? An introduction with Alex Tabarrok", 
  "content_type": "video/mp4", 
  "author": "Samuel Bryan", 
  "ver": "0.0.3", 
  "title": "What is LBRY?", 
  "sources": {
    "lbry_sd_hash": "d5169241150022f996fa7cd6a9a1c421937276a3275eb912790bd07ba7aec1fac5fd45431d226b8fb402691e79aeb24b"
  }, 
  "thumbnail": "https://s3.amazonaws.com/files.lbry.io/logo.png"
}

example_010 = {
  "version": "_0_0_1", 
  "claimType": "streamType", 
  "stream": {
    "source": {
      "source": "d5169241150022f996fa7cd6a9a1c421937276a3275eb912790bd07ba7aec1fac5fd45431d226b8fb402691e79aeb24b", 
      "version": "_0_0_1", 
      "contentType": "video/mp4", 
      "sourceType": "lbry_sd_hash"
    }, 
    "version": "_0_0_1", 
    "metadata": {
      "license": "LBRY Inc", 
      "description": "What is LBRY? An introduction with Alex Tabarrok", 
      "language": "en", 
      "title": "What is LBRY?", 
      "author": "Samuel Bryan", 
      "version": "_0_1_0", 
      "nsfw": False, 
      "licenseUrl": "", 
      "preview": "", 
      "thumbnail": "https://s3.amazonaws.com/files.lbry.io/logo.png"
    }
  }
}

example_010_serialized = "080110011adc010801129401080410011a0d57686174206973204c4252593f223057686174206973204c4252593f20416e20696e74726f64756374696f6e207769746820416c6578205461626172726f6b2a0c53616d75656c20427279616e32084c42525920496e6338004a2f68747470733a2f2f73332e616d617a6f6e6177732e636f6d2f66696c65732e6c6272792e696f2f6c6f676f2e706e6752005a001a41080110011a30d5169241150022f996fa7cd6a9a1c421937276a3275eb912790bd07ba7aec1fac5fd45431d226b8fb402691e79aeb24b2209766964656f2f6d7034"

claim_010_signed_nist256p = {
  "version": "_0_0_1", 
  "publisherSignature": {
    "certificateId": "63f2da17b0d90042c559cc73b6b17f853945c43e", 
    "signatureType": "NIST256p", 
    "version": "_0_0_1", 
    "signature": "ec117f5e16a911f704aab8efa9178b1cdfcad0ba8e571ba86a56ecdade129fdff60ff7dcf00355bda788020a43a40fbd55aaaa080c3555fd8f0a87612b62936a"
  }, 
  "claimType": "streamType", 
  "stream": {
    "source": {
      "source": "d5169241150022f996fa7cd6a9a1c421937276a3275eb912790bd07ba7aec1fac5fd45431d226b8fb402691e79aeb24b", 
      "version": "_0_0_1", 
      "contentType": "video/mp4", 
      "sourceType": "lbry_sd_hash"
    }, 
    "version": "_0_0_1", 
    "metadata": {
      "license": "LBRY Inc", 
      "description": "What is LBRY? An introduction with Alex Tabarrok", 
      "language": "en", 
      "title": "What is LBRY?", 
      "author": "Samuel Bryan", 
      "version": "_0_1_0", 
      "nsfw": False, 
      "licenseUrl": "", 
      "preview": "", 
      "thumbnail": "https://s3.amazonaws.com/files.lbry.io/logo.png"
    }
  }
}

claim_010_signed_nist384p = {
  "version": "_0_0_1", 
  "publisherSignature": {
    "certificateId": "63f2da17b0d90042c559cc73b6b17f853945c43e", 
    "signatureType": "NIST384p", 
    "version": "_0_0_1", 
    "signature": "18e56bb52872809ac598c366c5f0fa9ecbcadb01198b7150b0c4518049086b6b4f552f01d16eaf9cbbf061d8ee35520f8fe22f278a4d0aab5f9c8a4cadd38b6bd4bdbb3b4368e24c6e966ebc24684d24f3d19f5a3e4c7bf69273b0f94aa1c51b"
  }, 
  "claimType": "streamType", 
  "stream": {
    "source": {
      "source": "d5169241150022f996fa7cd6a9a1c421937276a3275eb912790bd07ba7aec1fac5fd45431d226b8fb402691e79aeb24b", 
      "version": "_0_0_1", 
      "contentType": "video/mp4", 
      "sourceType": "lbry_sd_hash"
    }, 
    "version": "_0_0_1", 
    "metadata": {
      "license": "LBRY Inc", 
      "description": "What is LBRY? An introduction with Alex Tabarrok", 
      "language": "en", 
      "title": "What is LBRY?", 
      "author": "Samuel Bryan", 
      "version": "_0_1_0", 
      "nsfw": False, 
      "licenseUrl": "", 
      "preview": "", 
      "thumbnail": "https://s3.amazonaws.com/files.lbry.io/logo.png"
    }
  }
}

claim_010_signed_secp256k1 = {
  "version": "_0_0_1", 
  "publisherSignature": {
    "certificateId": "63f2da17b0d90042c559cc73b6b17f853945c43e", 
    "signatureType": "SECP256k1", 
    "version": "_0_0_1", 
    "signature": "798a37bd4310339e6a9b424ebc3fd2b3263280c13c0d08b1d1fa5e53d29c102b2d340cedecc5018988819db0ac6eb61bf67dbeec4ebee7231668fd13931e6320"
  }, 
  "claimType": "streamType", 
  "stream": {
    "source": {
      "source": "d5169241150022f996fa7cd6a9a1c421937276a3275eb912790bd07ba7aec1fac5fd45431d226b8fb402691e79aeb24b", 
      "version": "_0_0_1", 
      "contentType": "video/mp4", 
      "sourceType": "lbry_sd_hash"
    }, 
    "version": "_0_0_1", 
    "metadata": {
      "license": "LBRY Inc", 
      "description": "What is LBRY? An introduction with Alex Tabarrok", 
      "language": "en", 
      "title": "What is LBRY?", 
      "author": "Samuel Bryan", 
      "version": "_0_1_0", 
      "nsfw": False, 
      "licenseUrl": "", 
      "preview": "", 
      "thumbnail": "https://s3.amazonaws.com/files.lbry.io/logo.png"
    }
  }
}

hex_encoded_003="7b22766572223a2022302e302e33222c20226465736372697074696f6e223a202274657374222c20226c6963656e7365223a2022437265617469766520436f6d6d6f6e73204174747269627574696f6e20342e3020496e7465726e6174696f6e616c222c2022617574686f72223a202274657374222c20227469746c65223a202274657374222c20226c616e6775616765223a2022656e222c2022736f7572636573223a207b226c6272795f73645f68617368223a2022323961643231386336316335393934393962323263313732323833373162356665396136653732356564633965663639316137383139623365373430363530303436373835323932303632396662636464626361636631336433313537396434227d2c2022636f6e74656e745f74797065223a2022696d6167652f706e67222c20226e736677223a2066616c73657d"

decoded_hex_encoded_003={u'version': u'_0_0_1', u'claimType': u'streamType', u'stream': {u'source': {u'source': '29ad218c61c599499b22c17228371b5fe9a6e725edc9ef691a7819b3e7406500467852920629fbcddbcacf13d31579d4', u'version': u'_0_0_1', u'contentType': u'image/png', u'sourceType': u'lbry_sd_hash'}, u'version': u'_0_0_1', u'metadata': {u'license': u'Creative Commons Attribution 4.0 International', u'description': u'test', u'language': u'en', u'title': u'test', u'author': u'test', u'version': u'_0_1_0', u'nsfw': False, u'licenseUrl': u'', u'preview': u'', u'thumbnail': u''}}}

binary_claim = b'\x08\x01\x10\x02"^\x08\x01\x10\x03"X0V0\x10\x06\x07*\x86H\xce=\x02\x01\x06\x05+\x81\x04\x00\n\x03B\x00\x04\x89U\x97\x1dk\xbc\xd4\xf7\xe2\xb5\xa9a7\xbc\xa4;\xda\x9a\x13\x84<\x05"\xa5\xc3\no;u\xb6\x8co\x10\x81\x8c\x1d\xf2\xe7\t\x9c.\xc8\x9b\x84\xabz:6\x15\xa5\xb3\x16\n\x03YT&M\x98\xec+\xef\x89;'
expected_binary_claim_decoded = {u'certificate': {u'keyType': u'SECP256k1',
                  u'publicKey': u'3056301006072a8648ce3d020106052b8104000a034200048955971d6bbcd4f7e2b5a96137bca43bda9a13843c0522a5c30a6f3b75b68c6f10818c1df2e7099c2ec89b84ab7a3a3615a5b3160a035954264d98ec2bef893b',
                  u'version': u'_0_0_1'},
                  u'claimType': u'certificateType',
                  u'version': u'_0_0_1'}