from lbry.schema.base import Signable


class Support(Signable):
    __slots__ = ()
    message_class = None  # TODO: add support protobufs
