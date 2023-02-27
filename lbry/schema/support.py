from lbry.schema.base import Signable
from lbry_types.v2.support_pb2 import Support as SupportMessage


class Support(Signable):
    __slots__ = ()
    message_class = SupportMessage

    @property
    def emoji(self) -> str:
        return self.message.emoji

    @emoji.setter
    def emoji(self, emoji: str):
        self.message.emoji = emoji

    @property
    def comment(self) -> str:
        return self.message.comment

    @comment.setter
    def comment(self, comment: str):
        self.message.comment = comment
