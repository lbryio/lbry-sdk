from lbry.schema.base import Signable
from lbry.schema.types.v2.support_pb2 import Support as SupportMessage


class Support(Signable):
    __slots__ = ()
    message_class = SupportMessage

    @property
    def emoji(self) -> str:
        return self.message.emoji

    @emoji.setter
    def emoji(self, emoji: str):
        self.message.emoji = emoji
