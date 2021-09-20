import asyncio
import logging

log = logging.getLogger(__name__)


class DiskSpaceManager:

    def __init__(self, config, db, blob_manager, cleaning_interval=30 * 60):
        self.config = config
        self.db = db
        self.blob_manager = blob_manager
        self.cleaning_interval = cleaning_interval
        self.running = False
        self.task = None

    async def get_space_used_bytes(self):
        return await self.db.get_stored_blob_disk_usage()

    async def get_space_used_mb(self):
        return int(await self.get_space_used_bytes()/1024.0/1024.0)

    async def clean(self):
        if not self.config.blob_storage_limit:
            return 0
        delete = []
        available = (self.config.blob_storage_limit*1024*1024) - await self.get_space_used_bytes()
        if available > 0:
            return 0
        for blob_hash, file_size, _ in await self.db.get_stored_blobs(is_mine=False):
            delete.append(blob_hash)
            available += file_size
            if available > 0:
                break
        if delete:
            await self.db.stop_all_files()
            await self.blob_manager.delete_blobs(delete, delete_from_db=True)
        return len(delete)

    async def cleaning_loop(self):
        while self.running:
            await asyncio.sleep(self.cleaning_interval)
            await self.clean()

    async def start(self):
        self.running = True
        self.task = asyncio.create_task(self.cleaning_loop())
        self.task.add_done_callback(lambda _: log.info("Stopping blob cleanup service."))

    async def stop(self):
        if self.running:
            self.running = False
            self.task.cancel()
