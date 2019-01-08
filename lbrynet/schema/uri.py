import re
from lbrynet.schema.error import URIParseError

PROTOCOL = 'lbry://'
CHANNEL_CHAR = '@'
CLAIM_ID_CHAR = '#'
CLAIM_SEQUENCE_CHAR = ':'
BID_POSITION_CHAR = '$'
PATH_CHAR = '/'
QUERY_CHAR = '?'

CLAIM_ID_MAX_LENGTH = 40
CHANNEL_NAME_MIN_LENGTH = 1


class URI(object):
    __slots__ = ['name', 'claim_sequence', 'bid_position', 'claim_id', 'path']

    def __init__(self, name, claim_sequence=None, bid_position=None, claim_id=None, path=None):
        if len([v for v in [claim_sequence, bid_position, claim_id] if v is not None]) > 1:
            raise ValueError(
                "Only one of these may be present at a time: claim_sequence, bid_position, claim_id"
            )

        self.name = name
        self.claim_sequence = claim_sequence
        self.bid_position = bid_position
        self.claim_id = claim_id
        self.path = path

        if self.path is not None and not self.contains_channel:
            raise ValueError("Content claims cannot have paths")

    def __str__(self):
        return self.to_uri_string()

    def __eq__(self, other):
        for prop in self.__slots__:
            if not hasattr(other, prop) or getattr(self, prop) != getattr(other, prop):
                return False
        return self.__class__ == other.__class__
    @property
    def channel_name(self):
        return self.name if self.contains_channel else None

    @property
    def claim_name(self):
        return self.name if not self.contains_channel else self.path

    @property
    def contains_channel(self):
        return self.name.startswith(CHANNEL_CHAR)

    @property
    def is_channel(self):
        return self.contains_channel and not self.path

    def to_uri_string(self):
        uri_string = PROTOCOL + "%s" % self.name

        if self.claim_sequence is not None:
            uri_string += CLAIM_SEQUENCE_CHAR + "%i" % self.claim_sequence
        elif self.bid_position is not None:
            uri_string += BID_POSITION_CHAR + "%i" % self.bid_position
        elif self.claim_id is not None:
            uri_string += CLAIM_ID_CHAR + "%s" % self.claim_id

        if self.path is not None:
            uri_string += PATH_CHAR + "%s" % self.path

        return uri_string

    def to_dict(self):
        return {
            "name": self.name,
            'claim_sequence': self.claim_sequence,
            'bid_position': self.bid_position,
            'claim_id': self.claim_id,
            'path': self.path,
        }

    @classmethod
    def from_uri_string(cls, uri_string):
        """
        Parses LBRY uri into its components

        :param uri_string: format - lbry://name:n$rank#id/path
                           optional modifiers:
                           claim_sequence (int): the nth claim to the name
                           bid_position (int): the bid queue position of the claim for the name
                           claim_id (str): the claim id for the claim
                           path (str): claim within a channel
        :return: URI
        """
        match = re.match(get_schema_regex(), uri_string)

        if match is None:
            raise URIParseError('Invalid URI')

        if match.group('content_name') and match.group('path'):
            raise URIParseError('Only channels may have paths')

        return cls(
            name=match.group("content_or_channel_name"),
            claim_sequence=int(match.group("claim_sequence")) if match.group(
                "claim_sequence") is not None else None,
            bid_position=int(match.group("bid_position")) if match.group(
                "bid_position") is not None else None,
            claim_id=match.group("claim_id"),
            path=match.group("path")
        )

    @classmethod
    def from_dict(cls, uri_dict):
        """
        Creates URI from dict

        :return: URI
        """
        return cls(**uri_dict)


def get_schema_regex():
    def _named(name, regex):
        return "(?P<" + name + ">" + regex + ")"

    def _group(regex):
        return "(?:" + regex + ")"

    # TODO: regex should include the fact that content names cannot have paths
    #       right now this is only enforced in code, not in the regex

    # Escape constants
    claim_id_char = re.escape(CLAIM_ID_CHAR)
    claim_sequence_char = re.escape(CLAIM_SEQUENCE_CHAR)
    bid_position_char = re.escape(BID_POSITION_CHAR)
    channel_char = re.escape(CHANNEL_CHAR)
    path_char = re.escape(PATH_CHAR)
    protocol = _named("protocol", re.escape(PROTOCOL))

    # Define basic building blocks
    valid_name_char = "[a-zA-Z0-9\-]"  # these characters are the only valid name characters
    name_content = valid_name_char + '+'
    name_min_channel_length = valid_name_char + '{' + str(CHANNEL_NAME_MIN_LENGTH) + ',}'

    positive_number = "[1-9][0-9]*"
    number = '\-?' + positive_number

    # Define URI components
    content_name = _named("content_name", name_content)
    channel_name = _named("channel_name", channel_char + name_min_channel_length)
    content_or_channel_name = _named("content_or_channel_name", content_name + "|" + channel_name)

    claim_id_piece = _named("claim_id", "[0-9a-f]{1," + str(CLAIM_ID_MAX_LENGTH) + "}")
    claim_id = _group(claim_id_char + claim_id_piece)

    bid_position_piece = _named("bid_position", number)
    bid_position = _group(bid_position_char + bid_position_piece)

    claim_sequence_piece = _named("claim_sequence", number)
    claim_sequence = _group(claim_sequence_char + claim_sequence_piece)

    modifier = _named("modifier", claim_id + "|" + bid_position + "|" + claim_sequence)

    path_piece = _named("path", name_content)
    path = _group(path_char + path_piece)

    # Combine components
    uri = _named("uri", (
        '^' +
        protocol + '?' +
        content_or_channel_name +
        modifier + '?' +
        path + '?' +
        '$'
    ))

    return uri


def parse_lbry_uri(lbry_uri):
    return URI.from_uri_string(lbry_uri)
