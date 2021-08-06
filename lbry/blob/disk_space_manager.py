import os


class DiskSpaceManager:

    def __init__(self, config):
        self.config = config

    @property
    def space_used_bytes(self):
        used = 0
        data_dir = self.config.data_dir
        for item in os.listdir(data_dir):
            blob_path = os.path.join(data_dir, item)
            if os.path.isfile(blob_path):
                used += os.path.getsize(blob_path)
        return used

    @property
    def space_used_mb(self):
        return int(self.space_used_bytes/1024.0/1024.0)
