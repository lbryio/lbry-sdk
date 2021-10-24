import asyncio

from lbry.stream.downloader import StreamDownloader


class BackgroundDownloader:
    def __init__(self, conf, storage, blob_manager, dht_node):
        self.storage = storage
        self.blob_manager = blob_manager
        self.node = dht_node
        self.conf = conf

    async def download_blobs(self, sd_hash):
        downloader = StreamDownloader(asyncio.get_running_loop(), self.conf, self.blob_manager, sd_hash)
        try:
            await downloader.start(self.node, save_stream=False)
        except ValueError:
            return
        for blob_info in downloader.descriptor.blobs[:-1]:
            await downloader.download_stream_blob(blob_info)
        await self.storage.set_announce(sd_hash, downloader.descriptor.blobs[0].blob_hash)