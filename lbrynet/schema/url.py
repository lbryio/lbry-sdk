import re
import unicodedata
from typing import NamedTuple, Tuple


def _create_url_regex():
    # see https://spec.lbry.io/

    def _named(name, regex):
        return "(?P<" + name + ">" + regex + ")"

    def _group(regex):
        return "(?:" + regex + ")"

    def _oneof(*choices):
        return _group('|'.join(choices))

    def _claim(name, prefix=""):
        return _group(
            _named(name+"_name", prefix + "[^=&#:$@%?/]+") +
            _oneof(
                _group('#' + _named(name+"_claim_id", "[0-9a-f]{1,40}")),
                _group(':' + _named(name+"_sequence", '[1-9][0-9]*')),
                _group(r'\$' + _named(name+"_amount_order", '[1-9][0-9]*'))
            ) + '?'
        )

    return (
        '^' +
        _named("scheme", "lbry://") + '?' +
        _oneof(
            _group(_claim("channel_with_stream", "@") + "/" + _claim("stream_in_channel")),
            _claim("channel", "@"),
            _claim("stream")
        ) +
        '$'
    )


URL_REGEX = _create_url_regex()


def normalize_name(name):
    return unicodedata.normalize('NFD', name).casefold()


class PathSegment(NamedTuple):
    name: str
    claim_id: str = None
    sequence: int = None
    amount_order: int = None

    @property
    def normalized(self):
        return normalize_name(self.name)

    def to_dict(self):
        q = {'name': self.name}
        if self.claim_id is not None:
            q['claim_id'] = self.claim_id
        if self.sequence is not None:
            q['sequence'] = self.sequence
        if self.amount_order is not None:
            q['amount_order'] = self.amount_order
        return q

    def __str__(self):
        if self.claim_id is not None:
            return f"{self.name}#{self.claim_id}"
        elif self.sequence is not None:
            return f"{self.name}:{self.sequence}"
        elif self.amount_order is not None:
            return f"{self.name}${self.amount_order}"
        return self.name


class URL(NamedTuple):
    stream: PathSegment
    channel: PathSegment

    @property
    def has_channel(self):
        return self.channel is not None

    @property
    def has_stream(self):
        return self.stream is not None

    @property
    def has_stream_in_channel(self):
        return self.has_channel and self.has_stream

    @property
    def parts(self) -> Tuple:
        if self.has_stream_in_channel:
            return self.channel, self.stream
        if self.has_channel:
            return self.channel,
        return self.stream,

    def __str__(self):
        return f"lbry://{'/'.join(str(p) for p in self.parts)}"

    @classmethod
    def parse(cls, url):
        match = re.match(URL_REGEX, url)

        if match is None:
            raise ValueError('Invalid LBRY URL')

        segments = {}
        parts = match.groupdict()
        for segment in ('channel', 'stream', 'channel_with_stream', 'stream_in_channel'):
            if parts[f'{segment}_name'] is not None:
                segments[segment] = PathSegment(
                    parts[f'{segment}_name'],
                    parts[f'{segment}_claim_id'],
                    parts[f'{segment}_sequence'],
                    parts[f'{segment}_amount_order']
                )

        if 'channel_with_stream' in segments:
            segments['channel'] = segments['channel_with_stream']
            segments['stream'] = segments['stream_in_channel']

        return cls(segments.get('stream', None), segments.get('channel', None))
