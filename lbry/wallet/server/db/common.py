import typing

CLAIM_TYPES = {
    'stream': 1,
    'channel': 2,
    'repost': 3,
    'collection': 4,
}

STREAM_TYPES = {
    'video': 1,
    'audio': 2,
    'image': 3,
    'document': 4,
    'binary': 5,
    'model': 6,
}

# 9/21/2020
MOST_USED_TAGS = {
    "gaming",
    "people & blogs",
    "entertainment",
    "music",
    "pop culture",
    "education",
    "technology",
    "blockchain",
    "news",
    "funny",
    "science & technology",
    "learning",
    "gameplay",
    "news & politics",
    "comedy",
    "bitcoin",
    "beliefs",
    "nature",
    "art",
    "economics",
    "film & animation",
    "lets play",
    "games",
    "sports",
    "howto & style",
    "game",
    "cryptocurrency",
    "playstation 4",
    "automotive",
    "crypto",
    "mature",
    "sony interactive entertainment",
    "walkthrough",
    "tutorial",
    "video game",
    "weapons",
    "playthrough",
    "pc",
    "anime",
    "how to",
    "btc",
    "fun",
    "ethereum",
    "food",
    "travel & events",
    "minecraft",
    "science",
    "autos & vehicles",
    "play",
    "politics",
    "commentary",
    "twitch",
    "ps4live",
    "love",
    "ps4",
    "nonprofits & activism",
    "ps4share",
    "fortnite",
    "xbox",
    "porn",
    "video games",
    "trump",
    "español",
    "money",
    "music video",
    "nintendo",
    "movie",
    "coronavirus",
    "donald trump",
    "steam",
    "trailer",
    "android",
    "podcast",
    "xbox one",
    "survival",
    "audio",
    "linux",
    "travel",
    "funny moments",
    "litecoin",
    "animation",
    "gamer",
    "lets",
    "playstation",
    "bitcoin news",
    "history",
    "xxx",
    "fox news",
    "dance",
    "god",
    "adventure",
    "liberal",
    "2020",
    "horror",
    "government",
    "freedom",
    "reaction",
    "meme",
    "photography",
    "truth",
    "health",
    "lbry",
    "family",
    "online",
    "eth",
    "crypto news",
    "diy",
    "trading",
    "gold",
    "memes",
    "world",
    "space",
    "lol",
    "covid-19",
    "rpg",
    "humor",
    "democrat",
    "film",
    "call of duty",
    "tech",
    "religion",
    "conspiracy",
    "rap",
    "cnn",
    "hangoutsonair",
    "unboxing",
    "fiction",
    "conservative",
    "cars",
    "hoa",
    "epic",
    "programming",
    "progressive",
    "cryptocurrency news",
    "classical",
    "jesus",
    "movies",
    "book",
    "ps3",
    "republican",
    "fitness",
    "books",
    "multiplayer",
    "animals",
    "pokemon",
    "bitcoin price",
    "facebook",
    "sharefactory",
    "criptomonedas",
    "cod",
    "bible",
    "business",
    "stream",
    "comics",
    "how",
    "fail",
    "nsfw",
    "new music",
    "satire",
    "pets & animals",
    "computer",
    "classical music",
    "indie",
    "musica",
    "msnbc",
    "fps",
    "mod",
    "sport",
    "sony",
    "ripple",
    "auto",
    "rock",
    "marvel",
    "complete",
    "mining",
    "political",
    "mobile",
    "pubg",
    "hip hop",
    "flat earth",
    "xbox 360",
    "reviews",
    "vlogging",
    "latest news",
    "hack",
    "tarot",
    "iphone",
    "media",
    "cute",
    "christian",
    "free speech",
    "trap",
    "war",
    "remix",
    "ios",
    "xrp",
    "spirituality",
    "song",
    "league of legends",
    "cat"
}

MATURE_TAGS = [
    'nsfw', 'porn', 'xxx', 'mature', 'adult', 'sex'
]


def normalize_tag(tag):
    return tag.replace(" ", "_").replace("&", "and").replace("-", "_")


COMMON_TAGS = {
    tag: normalize_tag(tag) for tag in list(MOST_USED_TAGS)
}

INDEXED_LANGUAGES = [
  'none',
  'en',
  'aa',
  'ab',
  'ae',
  'af',
  'ak',
  'am',
  'an',
  'ar',
  'as',
  'av',
  'ay',
  'az',
  'ba',
  'be',
  'bg',
  'bh',
  'bi',
  'bm',
  'bn',
  'bo',
  'br',
  'bs',
  'ca',
  'ce',
  'ch',
  'co',
  'cr',
  'cs',
  'cu',
  'cv',
  'cy',
  'da',
  'de',
  'dv',
  'dz',
  'ee',
  'el',
  'eo',
  'es',
  'et',
  'eu',
  'fa',
  'ff',
  'fi',
  'fj',
  'fo',
  'fr',
  'fy',
  'ga',
  'gd',
  'gl',
  'gn',
  'gu',
  'gv',
  'ha',
  'he',
  'hi',
  'ho',
  'hr',
  'ht',
  'hu',
  'hy',
  'hz',
  'ia',
  'id',
  'ie',
  'ig',
  'ii',
  'ik',
  'io',
  'is',
  'it',
  'iu',
  'ja',
  'jv',
  'ka',
  'kg',
  'ki',
  'kj',
  'kk',
  'kl',
  'km',
  'kn',
  'ko',
  'kr',
  'ks',
  'ku',
  'kv',
  'kw',
  'ky',
  'la',
  'lb',
  'lg',
  'li',
  'ln',
  'lo',
  'lt',
  'lu',
  'lv',
  'mg',
  'mh',
  'mi',
  'mk',
  'ml',
  'mn',
  'mr',
  'ms',
  'mt',
  'my',
  'na',
  'nb',
  'nd',
  'ne',
  'ng',
  'nl',
  'nn',
  'no',
  'nr',
  'nv',
  'ny',
  'oc',
  'oj',
  'om',
  'or',
  'os',
  'pa',
  'pi',
  'pl',
  'ps',
  'pt',
  'qu',
  'rm',
  'rn',
  'ro',
  'ru',
  'rw',
  'sa',
  'sc',
  'sd',
  'se',
  'sg',
  'si',
  'sk',
  'sl',
  'sm',
  'sn',
  'so',
  'sq',
  'sr',
  'ss',
  'st',
  'su',
  'sv',
  'sw',
  'ta',
  'te',
  'tg',
  'th',
  'ti',
  'tk',
  'tl',
  'tn',
  'to',
  'tr',
  'ts',
  'tt',
  'tw',
  'ty',
  'ug',
  'uk',
  'ur',
  'uz',
  've',
  'vi',
  'vo',
  'wa',
  'wo',
  'xh',
  'yi',
  'yo',
  'za',
  'zh',
  'zu'
]


class ResolveResult(typing.NamedTuple):
    name: str
    claim_hash: bytes
    tx_num: int
    position: int
    tx_hash: bytes
    height: int
    amount: int
    short_url: str
    is_controlling: bool
    canonical_url: str
    creation_height: int
    activation_height: int
    expiration_height: int
    effective_amount: int
    support_amount: int
    last_takeover_height: typing.Optional[int]
    claims_in_channel: typing.Optional[int]
    channel_hash: typing.Optional[bytes]
    reposted_claim_hash: typing.Optional[bytes]
