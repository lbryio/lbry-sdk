import asyncio
import logging

from lbry.stream.downloader import StreamDownloader


log = logging.getLogger(__name__)


class BackgroundDownloader:
    def __init__(self, conf, storage, blob_manager, dht_node=None):
        self.storage = storage
        self.blob_manager = blob_manager
        self.node = dht_node
        self.conf = conf

    async def download_blobs(self, sd_hash):
        downloader = StreamDownloader(asyncio.get_running_loop(), self.conf, self.blob_manager, sd_hash)
        try:
            await downloader.start(self.node, save_stream=False)
            for blob_info in downloader.descriptor.blobs[:-1]:
                await downloader.download_stream_blob(blob_info)
        except ValueError:
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.error("Unexpected download error on background downloader")
        finally:
            downloader.stop()
