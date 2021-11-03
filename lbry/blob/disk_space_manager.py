import asyncio
import logging

log = logging.getLogger(__name__)


class DiskSpaceManager:

    def __init__(self, config, db, blob_manager, cleaning_interval=30 * 60, analytics=None):
        self.config = config
        self.db = db
        self.blob_manager = blob_manager
        self.cleaning_interval = cleaning_interval
        self.running = False
        self.task = None
        self.analytics = analytics

    async def get_free_space_mb(self, is_network_blob=False):
        limit_mb = self.config.network_storage_limit if is_network_blob else self.config.blob_storage_limit
        space_used_mb = await self.get_space_used_mb()
        space_used_mb = space_used_mb['network_storage'] if is_network_blob else space_used_mb['content_storage']
        return max(0, limit_mb - space_used_mb)

    async def get_space_used_bytes(self):
        return await self.db.get_stored_blob_disk_usage()

    async def get_space_used_mb(self):
        space_used_bytes = await self.get_space_used_bytes()
        return {key: int(value/1024.0/1024.0) for key, value in space_used_bytes.items()}

    async def clean(self):
        await self._clean(False)
        await self._clean(True)

    async def _clean(self, is_network_blob=False):
        space_used_bytes = await self.get_space_used_bytes()
        if is_network_blob:
            space_used_bytes = space_used_bytes['network_storage']
        else:
            space_used_bytes = space_used_bytes['content_storage'] + space_used_bytes['private_storage']
        storage_limit_mb = self.config.network_storage_limit if is_network_blob else self.config.blob_storage_limit
        storage_limit = storage_limit_mb*1024*1024 if storage_limit_mb else None
        if self.analytics:
            asyncio.create_task(
                self.analytics.send_disk_space_used(space_used_bytes, storage_limit, is_network_blob)
            )
        if not storage_limit:
            return 0
        delete = []
        available = storage_limit - space_used_bytes
        if available > 0:
            return 0
        for blob_hash, file_size, _ in await self.db.get_stored_blobs(is_mine=False, is_network_blob=is_network_blob):
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
