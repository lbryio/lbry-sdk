import os
import asyncio
import logging

log = logging.getLogger(__name__)


class DiskSpaceManager:

    def __init__(self, config, cleaning_interval=30 * 60):
        self.config = config
        self.cleaning_interval = cleaning_interval
        self.running = False
        self.task = None

    @property
    def space_used_bytes(self):
        used = 0
        data_dir = os.path.join(self.config.data_dir, 'blobfiles')
        for item in os.scandir(data_dir):
            if item.is_file:
                used += item.stat().st_size
        return used

    @property
    def space_used_mb(self):
        return int(self.space_used_bytes/1024.0/1024.0)

    def clean(self):
        if not self.config.blob_storage_limit:
            return
        used = 0
        files = []
        data_dir = os.path.join(self.config.data_dir, 'blobfiles')
        for file in os.scandir(data_dir):
            if file.is_file:
                file_stats = file.stat()
                used += file_stats.st_size
                files.append((file_stats.st_mtime, file_stats.st_size, file.path))
        files.sort()
        available = (self.config.blob_storage_limit*1024*1024) - used
        for _, file_size, file in files:
            available += file_size
            if available > 0:
                break
            os.remove(file)

    async def cleaning_loop(self):
        while self.running:
            await asyncio.get_event_loop().run_in_executor(None, self.clean)
            await asyncio.sleep(self.cleaning_interval)

    async def start(self):
        self.running = True
        self.task = asyncio.create_task(self.cleaning_loop())
        self.task.add_done_callback(lambda _: log.info("Stopping blob cleanup service."))

    async def stop(self):
        if self.running:
            self.running = False
            self.task.cancel()
