import asyncio
import typing
import random

from lbrynet import conf
from lbrynet.extras.reflector import reflector

if typing.TYPE_CHECKING:
    from lbrynet.stream.descriptor import StreamDescriptor
    from lbrynet.blob.blob_manager import BlobFileManager

# TODO: reflect from stream
# TODO: reflecto from blob
# TODO: reflect from all saved blobs
# TODO: reflect from blob_hashes

