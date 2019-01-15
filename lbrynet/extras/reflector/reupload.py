import asyncio
import typing

# TODO: transactional client
# TODO: three-way handshake
# TODO: reflect stream

async def reflect_stream(descriptor: StreamDescriptor,
                         blob_manager: BlobFileManager,
                         reflector_url: str) -> typing.List[str]:
    # returns a list of blob hashes uploaded to the server
    ...

